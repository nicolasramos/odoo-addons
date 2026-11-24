# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Knowledge search over the document pages.

The bot answers from what the company wrote down, and says which page it used:
a citation turns an answer into something a person can check. To keep that
promise the quoted snippet is centred on the words that matched, and the link
is absolute, so it can be opened from wherever the answer was read.

People search with their own words, not with the wording of the page, so the
query is matched word by word and the pages are ranked by how many of those
words they carry. Matching the whole query as one string only works for robots:
"estado del pedido" has to find "Como consultar el estado de un pedido".
"""

import json
import logging
import re

from odoo import http
from odoo.http import request
from odoo.osv import expression
from odoo.tools import html2plaintext
from werkzeug.exceptions import HTTPException

try:
    from odoo.addons.mail_bot_odooclaw.controllers import security
except ImportError:  # pragma: no cover - the dependency guarantees it
    security = None

_logger = logging.getLogger(__name__)

# How much of the page is quoted back. Long enough to read as an answer, short
# enough that a chat message stays a message.
SNIPPET_CHARS = 300

# Words that carry no topic of their own. They appear in every page, so matching
# on them turns a search into "give me everything" and drowns the pages that
# actually answer the question.
_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
    "que", "en", "con", "por", "para", "al", "se", "su", "sus", "mi", "me", "nos",
    "lo", "es", "son", "como", "cuando", "donde", "algo", "sobre", "este", "esta",
    "the", "and", "for", "with", "from", "this", "that",
}


def _query_words(query):
    """Return the content words of a search, in the order they were written."""
    return [
        word
        for word in re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", query or "")
        if len(word) > 2 and word.lower() not in _STOPWORDS
    ]


def _snippet(content, words):
    """Return the window of the page around the words that matched.

    Cutting the first N characters quotes the opening of the page whatever the
    search actually matched, so the reader cannot check the answer against the
    page it came from. When the words are only in the title, the opening is the
    only thing there to show, and that is what is returned.
    """
    text = html2plaintext(content or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    position = min(
        (found for found in (lowered.find(word.lower()) for word in words) if found >= 0),
        default=-1,
    )
    if position < 0:
        return text[:SNIPPET_CHARS]
    start = max(0, position - SNIPPET_CHARS // 3)
    end = min(len(text), start + SNIPPET_CHARS)
    return "%s%s%s" % (
        "…" if start else "",
        text[start:end].strip(),
        "…" if end < len(text) else "",
    )


def _citation_url(env, page_id):
    """Build an absolute link to the page.

    The bot quotes a page to a person inside a chat message, so a relative
    backend path is not something they can open.
    """
    path = "/web#id=%d&model=document.page&view_type=form" % page_id
    base = env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
    return "%s%s" % (base, path) if base else path


def search_pages(env, query, limit=5):
    """Search document pages word by word and return JSON-ready rows.

    Every content word is looked up on its own and the pages are ranked by how
    many of them they contain, so a paraphrase reaches the page that answers
    it. Recency breaks the ties: a stale page that repeats a word is not better
    than the current one.
    """
    words = _query_words(query)
    if not words:
        return []
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    # Over-fetch before ranking: the best page is often not among the newest few.
    pages = (
        env["document.page"]
        .sudo()
        .search(
            expression.OR(
                ["|", ("name", "ilike", word), ("content", "ilike", word)]
                for word in words
            ),
            limit=limit * 4,
            order="write_date desc, id desc",
        )
    )
    lowered = [word.lower() for word in words]
    scored = []
    for page in pages:
        haystack = ((page.name or "") + " " + (page.content or "")).lower()
        score = sum(1 for word in lowered if word in haystack)
        when = page.write_date or page.create_date
        scored.append((score, when.isoformat() if when else "", page))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results = []
    for _score, _when, page in scored[:limit]:
        results.append(
            {
                "id": page.id,
                "name": page.name,
                "snippet": _snippet(page.content, words),
                "backend_url": _citation_url(env, page.id),
                "updated": page.write_date.isoformat() if page.write_date else "",
            }
        )
    return results


class OdooClawKnowledgeController(http.Controller):
    @http.route(
        "/odooclaw/knowledge/search",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def knowledge_search(self, **kwargs):
        try:
            security.authorize()
            payload = json.loads(request.httprequest.data)
            results = search_pages(
                request.env, payload.get("query"), payload.get("limit") or 5
            )
            return request.make_json_response({"ok": True, "results": results})
        except Exception as e:  # noqa: BLE001
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(_logger, "odooclaw_knowledge_search error")

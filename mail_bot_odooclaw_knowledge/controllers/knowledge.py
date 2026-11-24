# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Knowledge search over the document pages.

The bot answers from what the company wrote down, and says which page it used:
a citation turns an answer into something a person can check. To keep that
promise the quoted snippet is centred on the words that matched, and the link
is absolute, so it can be opened from wherever the answer was read.

The search is deliberately plain (name or content contains the words, newest
first). It is the same query a person would type in the page list, so whatever
they find there, the bot can find too.
"""

import json
import logging

from odoo import http
from odoo.http import request
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


def _snippet(content, query):
    """Return the window of the page around the words that matched.

    Cutting the first N characters quotes the opening of the page whatever the
    search actually matched, so the reader cannot check the answer against the
    page it came from. When the words are only in the title, the opening is the
    only thing there to show, and that is what is returned.
    """
    text = html2plaintext(content or "").strip()
    if not text:
        return ""
    position = text.lower().find(query.lower())
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
    """Search document pages and return JSON-ready rows with their link."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    pages = (
        env["document.page"]
        .sudo()
        .search(
            ["|", ("name", "ilike", query), ("content", "ilike", query)],
            limit=limit,
            order="write_date desc, id desc",
        )
    )
    results = []
    for page in pages:
        results.append(
            {
                "id": page.id,
                "name": page.name,
                "snippet": _snippet(page.content, query),
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

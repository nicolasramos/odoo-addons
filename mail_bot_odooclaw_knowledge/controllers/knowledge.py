# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Knowledge search over the OCA document pages.

The bot answers from what the company wrote down, and says which page it used:
a citation turns an answer into something a person can check.

The search is deliberately plain (name or content contains the words, newest
first). It is the same query a person would type in the page list, so whatever
they find there, the bot can find too.
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

_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
    "que", "en", "con", "por", "para", "al", "se", "su", "sus", "mi", "me", "nos",
    "lo", "es", "son", "como", "cuando", "donde", "algo", "sobre", "este", "esta",
    "the", "and", "for", "with", "from", "this", "that",
}


def search_pages(env, query, limit=5):
    """Search document pages word by word and return JSON-ready rows.

    The query is split into words because people do not search with the exact
    page wording: "estado del pedido" must find "Como consultar el estado de un
    pedido". Matching on the whole phrase only works for robots.
    """
    words = [
        word
        for word in re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", query or "")
        if len(word) > 2 and word.lower() not in _STOPWORDS
    ]
    if not words:
        return []
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    conditions = [
        ["|", ("name", "ilike", word), ("content", "ilike", word)]
        for word in words
    ]
    pages = (
        env["document.page"]
        .sudo()
        .search(
            expression.OR(conditions),
            limit=limit * 4,
            order="write_date desc, id desc",
        )
    )
    lowered = [word.lower() for word in words]
    scored = []
    for page in pages:
        haystack = ((page.name or "") + " " + (page.content or "")).lower()
        score = sum(1 for word in lowered if word in haystack)
        scored.append((score, page.write_date or page.create_date, page))
    scored.sort(key=lambda item: (item[0], item[1] or ""), reverse=True)
    results = []
    for _score, _date, page in scored[:limit]:
        results.append(
            {
                "id": page.id,
                "name": page.name,
                "snippet": html2plaintext(page.content or "")[:400],
                "backend_url": "/web#id=%d&model=document.page&view_type=form"
                % page.id,
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

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Knowledge search over the document pages.

The bot answers from what the company wrote down, and says which page it used:
a citation turns an answer into something a person can check.

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

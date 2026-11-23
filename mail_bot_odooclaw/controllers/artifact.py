# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw artifact endpoint.

The engine's artifact tool calls this when someone asks the assistant to keep
what it just made. The artifact belongs to the person in the conversation, not
to the service user, so the payload carries the user id.
"""

import json
import logging

from odoo import http
from odoo.http import request
from werkzeug.exceptions import HTTPException

from . import security

_logger = logging.getLogger(__name__)


class OdooClawArtifactController(http.Controller):
    @http.route(
        "/odooclaw/artifact",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def artifact_create(self, **kwargs):
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            name = (payload.get("name") or "").strip()
            if not name:
                return security.error_response("Missing name")

            artifact = (
                request.env["odooclaw.artifact"]
                .sudo()
                .create(
                    {
                        "name": name,
                        "artifact_type": payload.get("artifact_type") or "document",
                        "content": payload.get("content") or "",
                        "tag_list": payload.get("tags") or "",
                        "user_id": int(payload.get("user_id") or 0)
                        or request.env.uid,
                        "channel_id": int(payload.get("channel_id") or 0) or False,
                        "message_id": int(payload.get("message_id") or 0) or False,
                    }
                )
            )
            return request.make_json_response(
                {"ok": True, "id": artifact.id, "name": artifact.name}
            )

        except Exception as e:  # noqa: BLE001
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(_logger, "odooclaw_artifact_create error")

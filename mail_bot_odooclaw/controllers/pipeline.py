# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw pipeline result endpoint.

The engine owns the conversation; Odoo owns the data. When the engine has
decided, it reports here with the run id, and this endpoint applies the effect:

* ``observed``: the log only.
* ``drafted``: an internal note with the proposed reply, for a person to read
  before anyone outside does.
* ``sent``: a comment visible to the customer, written as the bot.
* ``escalated``: a mail activity for the pipeline's escalation user.
* ``failed`` / ``skipped``: the log only.

The token is the same service secret as the rest of the /odooclaw/ routes.
"""

import json
import logging

from odoo import http
from odoo.http import request
from werkzeug.exceptions import HTTPException

from . import security

_logger = logging.getLogger(__name__)

VALID_STATES = ("observed", "drafted", "sent", "escalated", "failed", "skipped")


class OdooClawPipelineController(http.Controller):
    @http.route(
        "/odooclaw/pipeline/finish",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def pipeline_finish(self, **kwargs):
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            run_id = int(payload.get("run_id") or 0)
            state = payload.get("state") or ""
            if state not in VALID_STATES:
                return security.error_response(
                    "Invalid state %r; expected one of %s"
                    % (state, ", ".join(VALID_STATES))
                )
            run = request.env["mail.odooclaw.pipeline.run"].sudo().browse(run_id)
            if not run.exists():
                return security.error_response("Run %s not found" % run_id)

            run.apply_result(
                state=state,
                body=payload.get("body") or "",
                decision=payload.get("decision") or "",
                error=payload.get("error") or "",
                escalate=bool(payload.get("escalate")),
            )
            return request.make_json_response(
                {"ok": True, "run_id": run.id, "state": run.state}
            )

        except Exception as e:  # noqa: BLE001
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(_logger, "odooclaw_pipeline_finish error")

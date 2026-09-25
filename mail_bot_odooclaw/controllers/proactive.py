# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw proactive routes.

Two routes, both authenticated with the shared service secret (or the IP
allowlist), and both deliberately narrow:

* ``POST /odooclaw/signal`` — Odoo asks "the user just opened this screen; what
  should you offer?". The Go engine answers, and Odoo itself posts the message.
  The decision never leaves Odoo in this flow, which keeps the round trip to one
  call and means a failure is a silent non-event rather than a broken UI.

* ``POST /odooclaw/notify`` — the reverse: OdooClaw (an agent, a cron, an
  external trigger) asks Odoo to post an UNSOLICITED message to a user's private
  bot chat.

Neither touches a business record's chatter. That is the whole point of the
separate route: ``/odooclaw/reply`` keeps its single-use token and its guarantee
that it only ever answers a human, and unsolicited writes are confined here,
where they can only reach the bot's own private conversation with a user.
"""

import json
import logging

from odoo import http
from odoo.http import request
from werkzeug.exceptions import HTTPException

from ..models.mail_odooclaw_area import post_proactive_message
from . import security

_logger = logging.getLogger(__name__)


class OdooClawProactiveController(http.Controller):
    @http.route(
        "/odooclaw/signal",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def odooclaw_signal(self, **kwargs):
        """Evaluate a signal and post the suggestion when the engine allows it.

        Expected payload::

            {
              "user_id": 7,          # mandatory; the user whose screen opened
              "model": "account.move",
              "view_id": 123,        # optional
              "action_id": 456       # optional
            }

        Response always includes ``speak`` and ``reason``: a silence is an
        answer, and it is the one an operator most often needs to see.
        """
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            user_id = payload.get("user_id")
            model_name = payload.get("model") or ""
            view_id = payload.get("view_id")
            action_id = payload.get("action_id")

            if not user_id:
                return security.error_response("Missing user_id")

            result = self._evaluate_and_post(user_id, model_name, view_id, action_id)
            return request.make_json_response(result)

        except Exception as e:
            # authorize() short-circuits by raising an HTTPException carrying the
            # JSON 401. Rethrowing it is what makes the status survive; catching
            # it here would turn every auth rejection into a 500.
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(_logger, "odooclaw_signal error")

    @http.route(
        "/odooclaw/notify",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def odooclaw_notify(self, **kwargs):
        """Post an unsolicited proactive message to a user's private bot chat.

        Expected payload::

            {
              "user_id": 7,
              "message": "...",
              "playbook_id": "contabilidad.unposted_invoices",
              "area": "contabilidad"
            }

        This route cannot post to a business record: the target is resolved from
        ``user_id`` and is always the bot's private channel with that user.
        """
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            user_id = payload.get("user_id")
            message = (payload.get("message") or "").strip()

            if not user_id or not message:
                return security.error_response("Missing user_id or message")

            try:
                msg = post_proactive_message(
                    request.env,
                    user_id,
                    message,
                    payload.get("playbook_id"),
                    payload.get("area"),
                )
            except ValueError as exc:
                # Expected refusals (unknown user, no channel) are 400s, not 500s.
                return security.error_response(str(exc))

            return request.make_json_response(
                {
                    "status": "ok",
                    "message_id": msg.id,
                    "channel_id": msg.res_id if msg.model == "discuss.channel" else False,
                }
            )

        except Exception as e:
            # authorize() short-circuits by raising an HTTPException carrying the
            # JSON 401. Rethrowing it is what makes the status survive; catching
            # it here would turn every auth rejection into a 500.
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(_logger, "odooclaw_notify error")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evaluate_and_post(self, user_id, model_name, view_id, action_id):
        """Resolve the area, ask the engine, and post when it says speak.

        The engine call is the ONLY network hop. When the engine is not
        configured or is unreachable we return a silent decision with an explicit
        reason instead of raising: a view open must never fail because the
        assistant is down.
        """
        area_rec = request.env["mail.odooclaw.area"].sudo().resolve_area(
            model_name, view_id, action_id
        )
        if not area_rec:
            return {
                "speak": False,
                "reason": "no hay área funcional para esta pantalla",
                "area": "",
            }

        counters = area_rec.counters_for(model_name)

        engine_url = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.proactive_url", "")
        )
        if not engine_url:
            return {
                "speak": False,
                "reason": "el motor de proactividad no está configurado "
                "(odooclaw.proactive_url)",
                "area": area_rec.area,
            }

        # Local import: requests is only needed on this path.
        import requests

        # The same shared secret the webhook and reply paths use, so there is one
        # service credential to rotate rather than two.
        token = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.reply_token", "")
        )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-OdooClaw-Token"] = token

        try:
            resp = requests.post(
                engine_url,
                json={
                    "user_id": user_id,
                    "area": area_rec.area,
                    "model": model_name,
                    "view_id": view_id or 0,
                    "counters": counters,
                },
                headers=headers,
                timeout=5,
            )
        except Exception:  # noqa: BLE001 - engine unreachable means silence
            _logger.warning(
                "odooclaw: proactive engine unreachable at %s", engine_url, exc_info=True
            )
            return {
                "speak": False,
                "reason": "el motor de proactividad no responde",
                "area": area_rec.area,
            }

        if resp.status_code != 200:
            return {
                "speak": False,
                "reason": "el motor de proactividad devolvió %s" % resp.status_code,
                "area": area_rec.area,
            }

        try:
            decision = resp.json()
        except ValueError:
            return {
                "speak": False,
                "reason": "respuesta ilegible del motor de proactividad",
                "area": area_rec.area,
            }

        if not decision.get("speak"):
            return {
                "speak": False,
                "reason": decision.get("reason", ""),
                "area": area_rec.area,
            }

        # The engine decided; Odoo delivers. Posting here (rather than having the
        # engine call back) keeps the whole decision inside the request scope of
        # the user who triggered it, so there is no window where a suggestion
        # arrives after the user has already navigated away and logged out.
        try:
            post_proactive_message(
                request.env,
                user_id,
                decision.get("message", ""),
                decision.get("playbook_id"),
                area_rec.area,
            )
        except ValueError as exc:
            return {"speak": False, "reason": str(exc), "area": area_rec.area}

        return {
            "speak": True,
            "reason": decision.get("reason", ""),
            "playbook_id": decision.get("playbook_id", ""),
            "area": area_rec.area,
            "message": decision.get("message", ""),
        }

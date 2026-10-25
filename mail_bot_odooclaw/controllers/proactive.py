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

from odoo import _, http
from odoo.http import request
from werkzeug.exceptions import Unauthorized

from ..utils.markdown_html import markdown_to_safe_html

_logger = logging.getLogger(__name__)


def _resolve_area(screen):
    """Return the area record for a screen name, or None."""
    area = request.env["mail.odooclaw.area"].sudo().search(
        [("area", "=", screen)], limit=1
    )
    return area or None


def _get_bot_user():
    """Return the bot user record.

    sudo(): the proactive routes are ``auth="public"``, so without superuser
    rights reading the bot's own ``res.users`` row is denied by record rules.
    """
    return request.env.ref(
        "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
    ).sudo()


def _get_service_secret():
    """Return the configured service secret."""
    icp = request.env["ir.config_parameter"].sudo()
    return icp.get_param("odooclaw.service_secret", "")


def _get_allowed_ips():
    """Return the configured allowed IP list."""
    icp = request.env["ir.config_parameter"].sudo()
    ips = icp.get_param("odooclaw.allowed_ips", "")
    return [ip.strip() for ip in ips.split(",") if ip.strip()] if ips else []


def _json_body():
    """Return the parsed JSON body of the request, or ``None``.

    Odoo 18 exposes ``request.get_json()``; Odoo 17 only has
    ``request.get_json_data()``, which raises on an empty or malformed body
    instead of returning a falsy value, so the callers' ``if not body`` guard
    needs this wrapper.
    """
    try:
        return request.get_json_data()
    except ValueError:
        return None


def _json_response(payload, status=200):
    """Return a plain JSON response (the routes are ``type="http"``)."""
    return request.make_json_response(payload, status=status)


def _error_response(reason, status=400):
    return _json_response({"status": "error", "reason": reason}, status=status)


def _authorize():
    """Authorize the request via service secret or IP allowlist.

    Raises ``Unauthorized`` (with a JSON body) on failure.
    """
    secret = _get_service_secret()
    if secret:
        token = request.httprequest.headers.get("X-OdooClaw-Token", "")
        if token == secret:
            return
    # Fallback to IP allowlist
    allowed_ips = _get_allowed_ips()
    if allowed_ips:
        client_ip = request.httprequest.remote_addr
        if client_ip in allowed_ips:
            return
    # Check X-Forwarded-For for proxied requests
    forwarded = request.httprequest.headers.get("X-Forwarded-For", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip in allowed_ips:
            return
    raise Unauthorized(
        response=_error_response(
            "Invalid or missing authentication token", status=401
        )
    )


class Proactive(http.Controller):
    """Proactive assistance endpoints."""

    def _post_to_bot_chat(self, user_id, message, area, playbook_id):
        """Post a proactive message to the bot's private chat with a user.

        This is the ONLY route in the module that writes without a human
        message behind it, so it is narrow, authenticated with the service
        secret (or the IP allowlist) and it can only ever target the bot's
        own private chat with a user — never a business record's chatter.

        Reuses ``_resolve_private_reply_channel`` so a proactive message lands in
        the same conversation the reply path uses, and posts as the bot user: the
        route is ``auth="public"``, so reading ``res.users`` or creating the
        channel needs superuser rights.
        """
        bot_user = _get_bot_user()
        if not bot_user:
            return None
        env = bot_user.env  # superuser
        user = env["res.users"].browse(int(user_id))
        if not user.exists() or not user.partner_id:
            return None

        channel = (
            env["mail.thread"]
            .sudo()
            ._resolve_private_reply_channel(user.partner_id, bot_user.partner_id)
        )
        if not channel:
            return None

        posted = (
            channel.with_user(bot_user)
            .sudo()
            .message_post(
                body=markdown_to_safe_html(message),
                author_id=bot_user.partner_id.id,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
        )
        # Odoo 17's message_post() rejects any kwarg that is not a supported
        # parameter, so the proactive markers are written on the created message.
        posted.sudo().write(
            {
                "odooclaw_proactive": True,
                "odooclaw_playbook_id": playbook_id or "",
                "odooclaw_area": area or "",
            }
        )

        # Stop typing indicator
        bot_member = channel.channel_member_ids.filtered(
            lambda member: member.partner_id == bot_user.partner_id
        )
        if bot_member:
            bot_member.sudo()._notify_typing(is_typing=False)

        _logger.info(
            "odooclaw: proactive message posted user_id=%s area=%s playbook=%s",
            user_id,
            area,
            playbook_id,
        )
        return posted

    @http.route("/odooclaw/signal", type="http", auth="public", methods=["POST"],
                csrf=False, website_published=False)
    def signal(self, **kwargs):
        """Evaluate a proactive signal and answer with the engine's decision.

        ``type="http"`` (not ``"json"``) on purpose: Odoo wraps a json route's
        result in a JSON-RPC envelope and turns every error — including an auth
        rejection — into HTTP 200, so the caller could not tell a refusal from a
        success. The module's other public route (``/odooclaw/reply``) already
        works this way.
        """
        _authorize()

        body = _json_body()
        if not body:
            return _error_response("empty body")

        user_id = body.get("user_id")
        screen = body.get("screen")
        if not user_id or not screen:
            return _error_response("missing user_id or screen")

        # Resolve area
        area_rec = _resolve_area(screen)
        if not area_rec:
            return _json_response(
                {
                    "status": "ok",
                    "speak": False,
                    "reason": _("no area for this screen"),
                    "area": "",
                }
            )

        # Call Go engine
        icp = request.env["ir.config_parameter"].sudo()
        webhook_url = icp.get_param(
            "odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo"
        )
        webhook_token = icp.get_param("odooclaw.webhook_token", "")

        payload = {
            "event": "signal",
            "user_id": user_id,
            "screen": screen,
            "area": area_rec.area,
        }

        try:
            import requests
            headers = {"Content-Type": "application/json"}
            if webhook_token:
                headers["X-OdooClaw-Token"] = webhook_token
            resp = requests.post(
                webhook_url, json=payload, headers=headers, timeout=10
            )
            resp.raise_for_status()
            decision = resp.json()
        except Exception as exc:
            return _json_response(
                {
                    "status": "ok",
                    "speak": False,
                    "reason": str(exc),
                    "area": area_rec.area,
                }
            )

        return _json_response(
            {
                "status": "ok",
                "speak": True,
                "reason": decision.get("reason", ""),
                "playbook_id": decision.get("playbook_id", ""),
                "area": area_rec.area,
                "message": decision.get("message", ""),
            }
        )

    @http.route("/odooclaw/notify", type="http", auth="public", methods=["POST"],
                csrf=False, website_published=False)
    def notify(self, **kwargs):
        """Handle a proactive notification from OdooClaw.

        OdooClaw posts an UNSOLICITED offer here; this controller resolves
        the private bot chat for the target user and posts the message there.
        """
        _authorize()

        body = _json_body()
        if not body:
            return _error_response("empty body")

        user_id = body.get("user_id")
        message = body.get("message")
        area = body.get("area", "")
        playbook_id = body.get("playbook_id", "")

        if not user_id or not message:
            return _error_response("missing user_id or message")

        posted_msg = self._post_to_bot_chat(user_id, message, area, playbook_id)
        if not posted_msg:
            return _error_response("bot user not configured")

        return _json_response({"status": "ok", "message_id": posted_msg.id})

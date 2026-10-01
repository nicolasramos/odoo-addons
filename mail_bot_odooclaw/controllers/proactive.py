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
from werkzeug.exceptions import Unauthorized, Forbidden

_logger = logging.getLogger(__name__)


def _resolve_area(screen):
    """Return the area record for a screen name, or None."""
    area = request.env["mail.odooclaw.area"].sudo().search(
        [("area", "=", screen)], limit=1
    )
    return area or None


def _get_bot_user():
    """Return the bot user record."""
    return request.env.ref(
        "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
    )


def _get_service_secret():
    """Return the configured service secret."""
    icp = request.env["ir.config_parameter"].sudo()
    return icp.get_param("odooclaw.service_secret", "")


def _get_allowed_ips():
    """Return the configured allowed IP list."""
    icp = request.env["ir.config_parameter"].sudo()
    ips = icp.get_param("odooclaw.allowed_ips", "")
    return [ip.strip() for ip in ips.split(",") if ip.strip()] if ips else []


def _authorize():
    """Authorize the request via service secret or IP allowlist.

    Raises ``Unauthorized`` or ``Forbidden`` on failure.
    """
    secret = _get_service_secret()
    if secret:
        token = request.headers.get("X-OdooClaw-Token", "")
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
    raise Unauthorized("Invalid or missing authentication token")


class Proactive(http.Controller):
    """Proactive assistance endpoints."""

    def _post_to_bot_chat(self, user_id, message, area, playbook_id):
        """Post a proactive message to the bot's private chat with a user.

        This is the ONLY route in the module that writes without a human
        message behind it, so it is narrow, authenticated with the service
        secret (or the IP allowlist) and it can only ever target the bot's
        own private chat with a user — never a business record's chatter.
        """
        bot = _get_bot_user()
        if not bot:
            return None

        # Find or create the bot channel for this user
        Channel = request.env["mail.channel"]
        domain = [
            ("channel_type", "=", "channel"),
            ("channel_last_notification_date", "=", False),
        ]
        # Find existing private channel between bot and user
        channels = Channel.sudo().search(domain)
        private_channel = None
        for ch in channels:
            if (
                bot.partner_id.id in ch.partner_ids.ids
                and user_id in ch.partner_ids.ids
            ):
                private_channel = ch
                break

        if not private_channel:
            # Create a new private channel
            user = request.env["res.users"].browse(user_id)
            private_channel = Channel.sudo().create(
                {
                    "name": bot.partner_id.name + " / " + user.name,
                    "channel_type": "channel",
                    "channel_last_notification_date": False,
                    "channel_is_private": True,
                    "channel_user_ids": [(4, user.partner_id.id)],
                    "channel_user_ids": [(4, bot.partner_id.id)],
                }
            )

        # Post the message
        values = {
            "body": message,
            "message_type": "comment",
            "model": private_channel._name,
            "res_id": private_channel.id,
            "odooclaw_proactive": True,
            "odooclaw_playbook_id": playbook_id,
            "odooclaw_area": area,
        }
        message = private_channel.message_post(**values)

        # Stop typing indicator
        bot_member = private_channel.channel_channel_member_ids.filtered(
            lambda m: m.partner_id.id == bot.partner_id.id
        )
        if bot_member:
            bot_member.sudo()._notify_typing(is_typing=False)

        _logger.info(
            "odooclaw: proactive message posted user_id=%s area=%s playbook=%s",
            user_id,
            area,
            playbook_id,
        )
        return message

    @http.route("/odooclaw/signal", type="json", auth="public", methods=["POST"],
                csrf=False, website_published=False)
    def signal(self, **kwargs):
        """Handle a proactive signal from the frontend.

        The frontend posts the current screen name and the user id.
        The controller resolves the area, calls the Go engine, and posts
        the result to the bot's private chat.
        """
        _authorize()

        body = request.get_json()
        if not body:
            return {"error": "empty body"}

        user_id = body.get("user_id")
        screen = body.get("screen")
        if not user_id or not screen:
            return {"error": "missing user_id or screen"}

        # Resolve area
        area_rec = _resolve_area(screen)
        if not area_rec:
            return {"speak": False, "reason": _("no area for this screen"), "area": ""}

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
            return {
                "speak": False,
                "reason": str(exc),
                "area": area_rec.area,
            }

        return {
            "speak": True,
            "reason": decision.get("reason", ""),
            "playbook_id": decision.get("playbook_id", ""),
            "area": area_rec.area,
            "message": decision.get("message", ""),
        }

    @http.route("/odooclaw/notify", type="json", auth="public", methods=["POST"],
                csrf=False, website_published=False)
    def notify(self, **kwargs):
        """Handle a proactive notification from OdooClaw.

        OdooClaw posts an UNSOLICITED offer here; this controller resolves
        the private bot chat for the target user and posts the message there.
        """
        _authorize()

        body = request.get_json()
        if not body:
            return {"error": "empty body"}

        user_id = body.get("user_id")
        message = body.get("message")
        area = body.get("area", "")
        playbook_id = body.get("playbook_id", "")

        if not user_id or not message:
            return {"error": "missing user_id or message"}

        posted_msg = self._post_to_bot_chat(user_id, message, area, playbook_id)
        if not posted_msg:
            return {"error": "bot user not configured"}

        return {"status": "ok", "message_id": posted_msg.id}

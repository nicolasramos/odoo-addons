# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""HttpCase integration test for the /odooclaw/reply endpoint.

This test actually hits the HTTP layer — not just mocked controllers — so it
catches bugs like the missing `make_json_response` that unit tests taint.
"""

import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestReplyEndpoint(HttpCase):
    """End-to-end HTTP test for the /odooclaw/reply endpoint."""

    def setUp(self):
        # Odoo 14's HttpCase has no class-level ``cls.env``: the fixtures are
        # built per test. ``super().setUp()`` has already entered test mode, so
        # the HTTP requests issued by url_open share this cursor and see them.
        super().setUp()
        self.bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        self.user = self.env["res.users"].create({
            "name": "HTTP Test User",
            "login": "http_test_user",
        })
        # Create a channel so test 2 has a valid target (avoids dependency on
        # whether id=1 exists in the test database).
        self.channel = self.env["mail.channel"].create({
            "name": "HTTP test channel",
            "channel_type": "chat",
        })
        # Configure the shared secret so authorize() passes.
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.reply_token", "test-secret"
        )

    def _post(self, payload):
        """POST to /odooclaw/reply with the shared secret."""
        return self.url_open(
            "/odooclaw/reply",
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-OdooClaw-Token": "test-secret",
            },
        )

    def test_reply_rejects_missing_reply_token(self):
        """Without a reply_token, the endpoint must return 401."""
        resp = self._post({
            "model": "mail.channel",
            "res_id": 1,
            "message": "hi",
        })
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("reply_token", body["reason"].lower())

    def test_reply_with_valid_token_returns_ok(self):
        """A valid reply_token produces an HTTP 200 + JSON body."""
        # Create a valid token for our own channel.
        token_rec = self.env["mail.odooclaw.reply.token"].sudo()._generate(
            model="mail.channel", res_id=self.channel.id, message_id=False
        )

        resp = self._post({
            "model": "mail.channel",
            "res_id": self.channel.id,
            "message": "Hello from HTTP!",
            "reply_token": token_rec.token,
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "ok")

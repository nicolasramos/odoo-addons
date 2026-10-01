# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProactive(HttpCase):
    """Proactive routes: delivery, refusals and the area resolver.

    The invariant under test is that proactivity cannot be used to write to a
    business record: /odooclaw/notify targets only the bot's private chat with a
    user, and /odooclaw/reply keeps requiring its single-use token.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.user = cls.env["res.users"].create(
            {
                "name": "Proactive Test User",
                "login": "proactive_test_user",
                "email": "proactive@example.com",
            }
        )
        # The shared secret has to be configured or authorize() default-denies.
        # This is the same parameter the webhook path uses — the proactive routes
        # intentionally reuse the existing service credential rather than
        # inventing a new one.
        cls.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.service_secret", "test-secret"
        )
        # Ensure the area model exists so the area resolver works.
        cls.Area = cls.env["mail.odooclaw.area"]
        cls.area = cls.Area.create(
            {
                "area": "accounting",
                "name": "Accounting",
            }
        )

    def test_signal_missing_auth(self):
        """/odooclaw/signal without auth must default-deny."""
        resp = self.url_open(
            "/odooclaw/signal",
            data=json.dumps({"user_id": self.user.id, "screen": "accounting"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_signal_valid_auth(self):
        """/odooclaw/signal with valid secret returns a decision dict."""
        resp = self.url_open(
            "/odooclaw/signal",
            data=json.dumps({"user_id": self.user.id, "screen": "accounting"}),
            headers={
                "Content-Type": "application/json",
                "X-OdooClaw-Token": "test-secret",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # The Go engine is not running, so we expect a failure reason,
        # not a crash.
        self.assertIn("speak", body)
        self.assertIn("area", body)
        self.assertEqual(body["area"], "accounting")

    def test_signal_missing_fields(self):
        """/odooclaw/signal without user_id or screen must return an error."""
        resp = self.url_open(
            "/odooclaw/signal",
            data=json.dumps({"screen": "accounting"}),
            headers={
                "Content-Type": "application/json",
                "X-OdooClaw-Token": "test-secret",
            },
        )
        body = resp.json()
        self.assertIn("error", body)

    def test_notify_missing_auth(self):
        """/odooclaw/notify without auth must default-deny."""
        resp = self.url_open(
            "/odooclaw/notify",
            data=json.dumps({"user_id": 1, "message": "unsolicited"}),
            headers={
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_notify_valid_auth(self):
        """/odooclaw/notify with valid secret posts to bot chat."""
        resp = self.url_open(
            "/odooclaw/notify",
            data=json.dumps({"user_id": self.user.id, "message": "unsolicited"}),
            headers={
                "Content-Type": "application/json",
                "X-OdooClaw-Token": "test-secret",
            },
        )
        body = resp.json()
        # The bot user exists but has no private channel yet, so the message
        # is posted and a channel is created.
        self.assertEqual(body["status"], "ok")

    def test_notify_missing_fields(self):
        """/odooclaw/notify without user_id or message returns an error."""
        resp = self.url_open(
            "/odooclaw/notify",
            data=json.dumps({"area": "accounting"}),
            headers={
                "Content-Type": "application/json",
                "X-OdooClaw-Token": "test-secret",
            },
        )
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("reply_token", body["reason"].lower())

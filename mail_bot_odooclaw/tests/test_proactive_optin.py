# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProactiveOptIn(TransactionCase):
    """The invitation asks once; a "sí" in the bot's private chat is the answer.

    The opt-in itself lives in the Go engine (it owns the policy, the cooldown
    and the dedupe). Odoo's job is to recognise the answer, report it to the
    engine and confirm it in the chat, and to do so BEFORE the webhook so the
    conversational agent does not also reply to it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.user = cls.env["res.users"].create(
            {
                "name": "OptIn Test User",
                "login": "optin_test_user",
                "email": "optin@example.com",
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param(
            "odooclaw.proactive_url", "http://engine:18790/odooclaw/signal"
        )
        params.set_param("odooclaw.reply_token", "test-secret")
        cls.channel = (
            cls.env["mail.thread"]
            .with_user(cls.user)
            .sudo()
            ._resolve_private_reply_channel(cls.user.partner_id, cls.bot.partner_id)
        )

    def _post_as_user(self, body):
        return (
            self.channel.with_user(self.user)
            .message_post(
                body=body,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
        )

    def _confirmations(self):
        return self.channel.message_ids.filtered(
            lambda m: m.body and "Sugerencias activadas" in m.body
        )

    def test_affirmative_reply_reports_the_optin(self):
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            post.return_value.status_code = 200
            self._post_as_user("sí")

        post.assert_called_once()
        called_url = post.call_args.args[0]
        self.assertTrue(
            called_url.endswith("/odooclaw/optin"),
            "the opt-in was not reported to the engine: %s" % called_url,
        )
        self.assertEqual(post.call_args.kwargs["json"]["user_id"], self.user.id)
        self.assertEqual(
            post.call_args.kwargs["headers"].get("X-OdooClaw-Token"),
            "test-secret",
        )

        confirmation = self.channel.message_ids.filtered(
            lambda m: m.body and "Sugerencias activadas" in m.body
        )
        self.assertTrue(confirmation, "the bot did not confirm the opt-in in the chat")
        self.assertEqual(
            confirmation.author_id,
            self.bot.partner_id,
            "the confirmation was not posted as the bot",
        )

    def test_a_rejected_optin_is_not_confirmed(self):
        """The engine said no, so the bot must not promise suggestions.

        The confirmation is a promise about the engine's behaviour. Posting it
        after a rejection tells the user something is on that is not, and the
        user has no way to find out.
        """
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            post.return_value.status_code = 502
            self._post_as_user("sí")

        post.assert_called_once()
        self.assertFalse(
            self._confirmations(),
            "the bot confirmed an opt-in the engine rejected",
        )

    def test_an_unreachable_engine_is_not_confirmed(self):
        """Same promise, same rule when the call does not come back at all."""
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            post.side_effect = ConnectionError("engine down")
            self._post_as_user("sí")

        self.assertFalse(
            self._confirmations(),
            "the bot confirmed an opt-in the engine never received",
        )

    def test_other_replies_do_not_report_the_optin(self):
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            self._post_as_user("hola, ¿qué tal?")

        optin_calls = [
            call
            for call in post.call_args_list
            if call.args and str(call.args[0]).endswith("/odooclaw/optin")
        ]
        self.assertFalse(optin_calls, "a normal reply was mistaken for the opt-in")

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

    def _deliver_invitation(self):
        """Put the engine's invitation in the chat the way the engine does.

        The engine sends ``system.invitation`` as the playbook of that one
        message and Odoo stamps it on what gets posted. That stamp is the only
        thing that tells a refusal apart from any other "no" in the chat.
        """
        from odoo.addons.mail_bot_odooclaw.models.mail_odooclaw_area import (
            post_proactive_message,
        )

        return post_proactive_message(
            self.env,
            self.user.id,
            "¿Te activo las sugerencias?",
            "system.invitation",
            "test",
        )

    def _bot_messages_after(self, message):
        return self.channel.message_ids.filtered(
            lambda m: m.author_id == self.bot.partner_id and m.id > message.id
        )

    def test_the_invitation_playbook_is_pinned(self):
        """The anchor is the engine's constant, not ours to drift.

        If the engine renames it, a refusal stops being recognised in silence,
        so the value is pinned here and the code names where it comes from.
        """
        from odoo.addons.mail_bot_odooclaw.models.mail_thread import MailThread

        self.assertEqual(
            MailThread._ODOOCLAW_INVITATION_PLAYBOOK, "system.invitation"
        )

    def test_a_no_to_the_invitation_is_acknowledged_once(self):
        self._deliver_invitation()
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            answer = self._post_as_user("no")

        post.assert_not_called()
        acks = self._bot_messages_after(answer)
        self.assertEqual(
            len(acks),
            1,
            "the answer to the invitation was not acknowledged exactly once",
        )
        self.assertNotIn(
            "Sugerencias activadas",
            acks[0].body or "",
            "a refusal was confirmed as an activation",
        )

    def test_a_no_without_an_invitation_stays_silent(self):
        """Outside the invitation, a "no" is an ordinary message."""
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            answer = self._post_as_user("no")

        self.assertFalse(
            self._bot_messages_after(answer),
            "a bare no produced a consent answer",
        )

    def test_a_no_after_another_suggestion_stays_silent(self):
        """The last proactive message decides, and here it is not the invitation."""
        from odoo.addons.mail_bot_odooclaw.models.mail_odooclaw_area import (
            post_proactive_message,
        )

        post_proactive_message(
            self.env,
            self.user.id,
            "Tienes tres facturas sin pagar.",
            "accounting.unposted_invoices",
            "test",
        )
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ):
            answer = self._post_as_user("no")

        # Outside the invitation a "no" is an ordinary message: the conversational
        # agent may well answer it, but nothing about consent is said.
        self.assertFalse(self._bot_messages_after(answer))

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

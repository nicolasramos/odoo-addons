from unittest.mock import Mock, patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailThreadWebhook(TransactionCase):
    def setUp(self):
        super().setUp()
        self.bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        self.user = self.env.ref("base.user_admin")
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.webhook_url", "http://odooclaw.test/webhook/odoo"
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.webhook_token", "test-shared-token"
        )

    def _channel(self, channel_type):
        return self.env["discuss.channel"].create(
            {
                "name": "OdooClaw test channel",
                "channel_type": channel_type,
                "channel_member_ids": [
                    (0, 0, {"partner_id": self.user.partner_id.id}),
                    (0, 0, {"partner_id": self.bot.partner_id.id}),
                ],
            }
        )

    @patch("odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post")
    def test_direct_message_dispatches_after_commit(self, post):
        post.return_value = Mock(status_code=200)
        channel = self._channel("chat")

        message = channel.with_user(self.user).message_post(body="hello")
        self.assertFalse(post.called, "Webhook must wait for the transaction commit")

        self.env.cr.commit()

        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["message_id"], message.id)
        self.assertEqual(payload["model"], "discuss.channel")
        self.assertEqual(payload["res_id"], channel.id)
        self.assertTrue(payload["is_dm"])
        self.assertEqual(payload["author_id"], self.user.partner_id.id)
        self.assertTrue(payload["reply_token"])

    @patch("odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post")
    def test_group_mention_keeps_group_as_reply_target(self, post):
        post.return_value = Mock(status_code=200)
        channel = self._channel("channel")

        message = channel.with_user(self.user).message_post(
            body="hello", partner_ids=[self.bot.partner_id.id]
        )
        self.env.cr.commit()

        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["message_id"], message.id)
        self.assertFalse(payload["is_dm"])
        self.assertEqual(payload["reply_model"], "discuss.channel")
        self.assertEqual(payload["reply_res_id"], channel.id)

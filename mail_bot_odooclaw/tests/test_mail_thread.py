# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Tests for the Odoo 14-specific message_post override and channel resolution.

These tests verify the two core acceptance criteria:
1. The module installs and its tests pass in Odoo 14.
2. The message_post override works correctly against a real installation.

Odoo 14 uses `mail.channel` (not `discuss.channel` from 16+) and
`message_post` is already keyword-only — the override uses **kwargs
so it passes cleanly through the core.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailChannelResolution(TransactionCase):
    """Test that _resolve_private_reply_channel works with mail.channel."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.user = cls.env["res.users"].create({
            "name": "Channel Test User",
            "login": "channel_test_user",
            "email": "channel@example.com",
        })

    def test_resolve_creates_private_chat_channel(self):
        """_resolve_private_reply_channel creates a mail.channel of type 'chat'."""
        channel = self.env["mail.thread"].sudo()._resolve_private_reply_channel(
            self.user.partner_id, self.bot.partner_id
        )
        self.assertEqual(channel.channel_type, "chat")
        self.assertIn(self.user.partner_id, channel.channel_member_ids.partner_id)
        self.assertIn(self.bot.partner_id, channel.channel_member_ids.partner_id)

    def test_resolve_reuses_existing_channel(self):
        """Two calls with the same partners must return the same channel."""
        first = self.env["mail.thread"].sudo()._resolve_private_reply_channel(
            self.user.partner_id, self.bot.partner_id
        )
        second = self.env["mail.thread"].sudo()._resolve_private_reply_channel(
            self.user.partner_id, self.bot.partner_id
        )
        self.assertEqual(first.id, second.id)

    def test_different_users_get_different_channels(self):
        """Different users must not share the same private channel."""
        other_user = self.env["res.users"].create({
            "name": "Other Test User",
            "login": "other_test_user",
        })
        ch1 = self.env["mail.thread"].sudo()._resolve_private_reply_channel(
            self.user.partner_id, self.bot.partner_id
        )
        ch2 = self.env["mail.thread"].sudo()._resolve_private_reply_channel(
            other_user.partner_id, self.bot.partner_id
        )
        self.assertNotEqual(ch1.id, ch2.id)


@tagged("post_install", "-at_install")
class TestMessagePostOverride(TransactionCase):
    """Test that the message_post override works with mail.channel in Odoo 14."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.user = cls.env["res.users"].create({
            "name": "Post Test User",
            "login": "post_test_user",
        })

    def test_message_post_on_channel(self):
        """message_post on a mail.channel works and returns the message."""
        channel = self.env["mail.channel"].create({
            "name": "Test Channel",
            "channel_type": "chat",
        })
        msg = channel.sudo().message_post(
            body="Test message",
            author_id=self.user.partner_id.id,
            message_type="comment",
        )
        self.assertTrue(msg.exists())
        self.assertEqual(msg.model, "mail.channel")
        self.assertEqual(msg.res_id, channel.id)

    def test_message_post_body_as_keyword(self):
        """message_post also works when body is passed as keyword."""
        channel = self.env["mail.channel"].create({
            "name": "Test Channel Keyword",
            "channel_type": "chat",
        })
        msg = channel.sudo().message_post(body="Test body keyword")
        self.assertTrue(msg.exists())
        self.assertIn("Test body keyword", msg.body)

    def test_message_post_with_author_and_partner_ids(self):
        """message_post with author_id and partner_ids works."""
        channel = self.env["mail.channel"].create({
            "name": "Test Channel Mentions",
            "channel_type": "chat",
        })
        msg = channel.sudo().message_post(
            body="Test with mention",
            author_id=self.user.partner_id.id,
            partner_ids=[self.user.partner_id.id],
            message_type="comment",
        )
        self.assertTrue(msg.exists())
        self.assertIn(self.user.partner_id, msg.partner_ids)

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Who may be offered proactive help.

Nico's rule: ANY INTERNAL DU user. Not portal, not public, not "some group".

These tests exist because the failure they prevent is silent and one-directional:
an audience that is too narrow means nobody is ever helped and no error is
raised, so the feature looks broken for no visible reason. An audience that is
too WIDE leaks business figures (unposted invoices, bank lines) to someone
outside the company — a data leak wearing the costume of a helpful message.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOdooclawAudience(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Users = cls.env["res.users"].sudo()
        cls.Audience = cls.env["mail.odooclaw.audience"].sudo()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")

        cls.internal = cls.Users.create(
            {
                "name": "Audience Internal",
                "login": "audience_internal@example.com",
                "email": "audience_internal@example.com",
                "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )
        cls.portal = cls.Users.create(
            {
                "name": "Audience Portal",
                "login": "audience_portal@example.com",
                "email": "audience_portal@example.com",
                "groups_id": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )
        cls.public = cls.env.ref("base.public_user")

        cls.audience = cls.Audience.create(
            {
                "name": "Test audience",
                "internal_only": True,
                "include_inactive": False,
            }
        )

    def test_internal_user_is_eligible(self):
        """An internal user without any special groups is eligible."""
        result = self.Audience.resolve_for_user(self.internal.id)
        self.assertTrue(result["eligible"], result["reason"])

    def test_portal_user_is_excluded(self):
        """A portal user (share=True) is never eligible."""
        result = self.Audience.resolve_for_user(self.portal.id)
        self.assertFalse(result["eligible"])
        self.assertIn("portal", result["reason"].lower())

    def test_public_user_is_excluded(self):
        """The public user is never eligible."""
        result = self.Audience.resolve_for_user(self.public.id)
        self.assertFalse(result["eligible"])

    def test_bot_user_is_excluded(self):
        """The bot user itself is never in the candidate list."""
        ids = self.audience.get_candidate_user_ids()
        self.assertNotIn(self.bot.id, ids)

    def test_admin_is_internal_and_eligible(self):
        """The baseline: a plain internal user is eligible, with no groups set."""
        admin = self.env.ref("base.user_admin")
        result = self.Audience.resolve_for_user(admin.id)
        self.assertTrue(result["eligible"], result["reason"])

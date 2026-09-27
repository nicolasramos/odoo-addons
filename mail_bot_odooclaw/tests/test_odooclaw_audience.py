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
                "login": "audience_internal@example.test",
                "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )
        cls.portal = cls.Users.create(
            {
                "name": "Audience Portal",
                "login": "audience_portal@example.test",
                "groups_id": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )

    def test_audience_row_is_shipped(self):
        """A fresh install already has the DU rule, not an empty config.

        An empty audience means nobody qualifies (fail-closed), so shipping
        without a default row would make the feature silently dead on install.
        """
        row = self.env.ref("mail_bot_odooclaw.audience_du_internal")
        self.assertTrue(row.internal_only)
        self.assertFalse(row.include_inactive)
        # No group restriction: DU means any internal user.
        self.assertFalse(row.group_ids)

    def test_internal_user_is_eligible(self):
        result = self.Audience.resolve_for_user(self.internal.id)
        self.assertTrue(result["eligible"], result["reason"])
        self.assertTrue(result["is_internal"])

    def test_portal_user_is_not_eligible(self):
        """The rule that matters: a portal user must never be offered help."""
        result = self.Audience.resolve_for_user(self.portal.id)
        self.assertFalse(result["eligible"])
        self.assertFalse(result["is_internal"])
        self.assertTrue(result["reason"])

    def test_public_user_is_not_eligible(self):
        public = self.env.ref("base.public_user", raise_if_not_found=False)
        if not public:
            self.skipTest("no public user in this database")
        result = self.Audience.resolve_for_user(public.id)
        self.assertFalse(result["eligible"])

    def test_bot_never_offers_help_to_itself(self):
        """The bot is an internal user; offering it help would be self-talk."""
        result = self.Audience.resolve_for_user(self.bot.id)
        self.assertFalse(result["eligible"])

    def test_deactivated_user_is_not_eligible(self):
        self.internal.active = False
        result = self.Audience.resolve_for_user(self.internal.id)
        self.assertFalse(result["eligible"])
        # The classification is still reported correctly: the user IS internal,
        # they are simply disabled. Conflating the two would hide a real bug.
        self.assertTrue(result["is_internal"])
        self.assertFalse(result["is_active"])

    def test_nonexistent_user_is_not_eligible(self):
        result = self.Audience.resolve_for_user(999999999)
        self.assertFalse(result["eligible"])

    def test_without_audience_everyone_is_excluded(self):
        """Fail-closed: an unconfigured audience must never mean "everybody"."""
        self.Audience.search([]).write({"active": False})
        result = self.Audience.resolve_for_user(self.internal.id)
        self.assertFalse(result["eligible"])
        # Assert on the SOURCE string (English since NRA-3914). The Spanish the
        # user reads lives in i18n/es.po, so asserting on it here would make the
        # test depend on the translation file rather than on this behaviour.
        self.assertIn("no audience is configured", result["reason"])

    def test_eligible_user_ids_excludes_portal_and_bot(self):
        ids = self.env.ref("mail_bot_odooclaw.audience_du_internal").eligible_user_ids()
        self.assertIn(self.internal.id, ids)
        self.assertNotIn(self.portal.id, ids)
        self.assertNotIn(self.bot.id, ids)

    def test_admin_is_internal_and_eligible(self):
        """The baseline: a plain internal user is eligible, with no groups set."""
        admin = self.env.ref("base.user_admin")
        result = self.Audience.resolve_for_user(admin.id)
        self.assertTrue(result["eligible"], result["reason"])

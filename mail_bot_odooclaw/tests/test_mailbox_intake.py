# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Dedicated mailbox intake (NRA-5531 / T9).

The acceptance criteria this file exists to prove:

    1. An email from a recognised employee with a ticket dispatches to
       OdooClaw, which creates that employee's expense (criterion 1).
    2. An unknown sender creates NO expense and the intake goes to the review
       queue with a reason (criterion 2 / D2).

The mailbox is fail-closed (D7): with the switch off nothing is processed. The
employee is resolved BY SENDER (partner -> user -> employee); a sender that does
not resolve to an employee never creates an expense.

The OdooClaw intake endpoint is external, so the dispatch step is patched in the
tests: the assertions are on the deterministic addon logic (who is dispatched,
who is reviewed, who is skipped), not on the remote call.

Assertions are on the English source strings (house rule): the Spanish the user
reads lives in i18n/es.po, and tests must not depend on the translation file.
"""

from base64 import b64encode
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailboxIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Intake = cls.env["odooclaw.document.intake"].sudo()
        cls.icp = cls.env["ir.config_parameter"].sudo()
        cls.sender = cls.env["res.partner"].create(
            {"name": "Ana Ruiz", "email": "ana@ejemplo.com"}
        )
        cls.user = cls.env["res.users"].create(
            {"name": "Ana Ruiz", "login": "ana@ejemplo.com", "partner_id": cls.sender.id}
        )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Ana Ruiz", "user_id": cls.user.id}
        )
        cls.other = cls.env["res.partner"].create(
            {"name": "Desconocido", "email": "extra@fuera.com"}
        )
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "ticket-ejemplo.pdf",
                "mimetype": "application/pdf",
                "datas": b64encode(b"%PDF-1.4 fake ticket for mailbox tests"),
            }
        )

    def _mailbox_intake(self):
        """A gateway-created mailbox intake (state new, not gated at create)."""
        return self.Intake.create(
            {
                "source": "mailbox",
                "intake_type": "expense",
                "attachment_id": self.attachment.id,
                "company_id": self.env.company.id,
            }
        )

    def _email_message(self, intake, partner):
        """Simulate the incoming email the gateway receives on the intake."""
        intake.message_post(
            body="Ticket de gastos",
            author_id=partner.id,
            message_type="email",
        )

    # -- employee resolution (D2) --------------------------------------------

    def test_resolve_employee_for_known_sender(self):
        intake = self._mailbox_intake()
        resolved = intake._resolve_employee_for_partner(self.sender)
        self.assertEqual(resolved, self.employee)

    def test_resolve_employee_for_unknown_sender(self):
        intake = self._mailbox_intake()
        resolved = intake._resolve_employee_for_partner(self.other)
        self.assertFalse(resolved)

    def test_no_employee_when_sender_is_not_a_user(self):
        # A partner that exists but has no Odoo user cannot yield an employee.
        stranger = self.env["res.partner"].create(
            {"name": "Sin usuario", "email": "sin@ejemplo.com"}
        )
        intake = self._mailbox_intake()
        self.assertFalse(intake._resolve_employee_for_partner(stranger))

    # -- the mailbox gate (D7) -----------------------------------------------

    def test_mailbox_off_does_not_dispatch(self):
        """With the mailbox flow off, nothing is dispatched and nothing is
        reviewed: the document stays declared and traceable (fail-closed)."""
        # Switch off by default.
        intake = self._mailbox_intake()
        self._email_message(intake, self.sender)
        with patch.object(
            type(intake), "_mailbox_dispatch_to_odooclaw"
        ) as dispatch:
            intake._process_incoming_mailbox_email()
        dispatch.assert_not_called()
        self.assertEqual(intake.state, "new")

    def test_mailbox_on_still_needs_an_allowed_sender(self):
        self.icp.set_param("odooclaw.intake.mailbox.enabled", "True")
        self.icp.set_param("odooclaw.intake.sender_allowlist", "trusted@ejemplo.com")
        intake = self._mailbox_intake()
        self._email_message(intake, self.sender)  # ana@ejemplo.com, not allowed
        with patch.object(
            type(intake), "_mailbox_dispatch_to_odooclaw"
        ) as dispatch:
            intake._process_incoming_mailbox_email()
        dispatch.assert_not_called()
        self.assertEqual(intake.state, "review")
        self.assertIn("allowlist", intake.reason)

    # -- criterion 2: unknown sender -> no expense, review -------------------

    def test_unknown_sender_creates_no_expense_and_reviews(self):
        """D2: a sender that does not resolve to an employee creates nothing and
        waits in the review queue with a reason."""
        self.icp.set_param("odooclaw.intake.mailbox.enabled", "True")
        self.icp.set_param("odooclaw.intake.sender_allowlist", "*")
        intake = self._mailbox_intake()
        self._email_message(intake, self.other)
        with patch.object(
            type(intake), "_mailbox_dispatch_to_odooclaw"
        ) as dispatch:
            intake._process_incoming_mailbox_email()
        dispatch.assert_not_called()
        self.assertEqual(intake.state, "review")
        self.assertFalse(intake.created_model)
        self.assertFalse(intake.created_res_id)
        self.assertIn("employee", intake.reason.lower())

    # -- criterion 1: known employee -> dispatched ---------------------------

    def test_known_employee_is_dispatched(self):
        """Criterion 1: an email from a recognised employee is dispatched to
        OdooClaw (which creates that employee's expense and writes it back)."""
        self.icp.set_param("odooclaw.intake.mailbox.enabled", "True")
        self.icp.set_param("odooclaw.intake.sender_allowlist", "*")
        intake = self._mailbox_intake()
        self._email_message(intake, self.sender)
        with patch.object(
            type(intake), "_mailbox_dispatch_to_odooclaw"
        ) as dispatch:
            intake._process_incoming_mailbox_email()
        dispatch.assert_called_once()
        # Dispatched for THIS employee's Odoo user (the sender the skill maps
        # back to the employee).
        self.assertEqual(dispatch.call_args[0][0], self.employee)

    def test_star_allowlist_admits_everyone(self):
        intake = self._mailbox_intake()
        self.icp.set_param("odooclaw.intake.sender_allowlist", "*")
        self.assertTrue(intake._mailbox_sender_allowed())

    def test_empty_allowlist_admits_nobody(self):
        """Empty allowlist is fail-closed (no open door): nobody is processed
        until the customer configures it."""
        intake = self._mailbox_intake()
        self.assertFalse(intake._mailbox_sender_allowed())

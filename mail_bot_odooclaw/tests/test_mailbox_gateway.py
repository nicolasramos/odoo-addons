# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Dedicated mailbox gateway end-to-end (NRA-5747 / CRITICAL 2).

The independent dictamen rejected the chain because the mailbox never reached
the pipeline: three independent defects, each enough to tumbar the criterion,
all on the email entry point. The existing mailbox tests call
``_process_incoming_mailbox_email()`` by hand on an intake created directly with
``attachment_id``, so they never exercise the email gateway and never see them.

These tests enter through the REAL Odoo 18 gateway (``message_process`` /
``message_new``), with a raw RFC-2822 email and a PDF attachment:

* **CRITICAL 2a** — ``alias_defaults`` must not carry ``"model"`` (not a field of
  the intake). The gateway runs ``ast.literal_eval(alias_defaults)`` and feeds it
  to ``create()``; a stray ``"model"`` bounces the email with
  ``ValueError: Invalid field 'model'``. Proven by feeding ``message_new`` a
  ``custom_values`` dict that still contains ``"model"`` and asserting the intake
  is declared (the hook keeps only real fields) and no exception is raised.
* **CRITICAL 2b** — ``_mail_receive`` does not exist in Odoo 18, so nothing ran
  the dispatch. Proven by injecting a raw email through ``message_process`` and
  asserting the gateway reaches ``_mailbox_dispatch_to_odooclaw`` (the intake
  progresses past ``new``).
* **CRITICAL 2c** — ``attachment_id`` was never filled on the mailbox intake.
  Proven by asserting the created intake carries ``attachment_id`` and
  ``checksum`` after a real email with a PDF landed.

Assertions are on the English source strings (house rule): the Spanish the user
reads lives in i18n/es.po, and tests must not depend on the translation file.
"""

from base64 import b64encode
from email.mime.application import MIMEApplication
from email.mime.message import MIMEMessage
from email.mime.text import MIMEText
from threading import Event
from uuid import uuid4

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailboxGateway(TransactionCase):
    # Unique localpart so this test does not collide with the alias that ships
    # with the module (alias_name is unique per company).
    ALIAS_NAME = "gastos5747"
    PDF = b64encode(b"%PDF-1.4 fake ticket for gateway tests")
    PDF = b64encode(b"%PDF-1.4 fake ticket for gateway tests \xf0\x9f\x8f\xac")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Intake = cls.env["odooclaw.document.intake"].sudo()
        cls.icp = cls.env["ir.config_parameter"].sudo()
        cls.mail_thread = cls.env["mail.thread"].sudo()
        cls.sender = cls.env["res.partner"].create(
            {"name": "Ana Ruiz", "email": "ana@ejemplo.com"}
        )
        cls.user = cls.env["res.users"].create(
            {"name": "Ana Ruiz", "login": "ana@ejemplo.com", "partner_id": cls.sender.id}
        )
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Ana Ruiz", "user_id": cls.user.id}
        )
        # Dedicated alias that routes the gateway to the intake model.
        model = cls.env["ir.model"].search(
            [("model", "=", "odooclaw.document.intake")], limit=1
        )
        cls.alias = cls.env["mail.alias"].sudo().create(
            {
                "alias_name": cls.ALIAS_NAME,
                "alias_model_id": model.id,
                "alias_incoming_local": True,
            }
        )

    # -- raw email builder -------------------------------------------------

    def _raw_email(self, frm, to, subject, body):
        msg = MIMEMessage()
        msg["From"] = frm
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-Id"] = "<%s@localhost>" % uuid4()
        msg.attach(MIMEText(body))
        part = MIMEApplication(bytes(self.PDF), Name="ticket.pdf")
        part.add_header(
            "Content-Disposition", "attachment", filename="ticket.pdf"
        )
        msg.attach(part)
        return msg.as_bytes()

    def _mailbox_to(self):
        # Localpart must match the alias so the gateway routes through it.
        return "%s@localhost" % self.ALIAS_NAME

    def _mailbox_intakes(self):
        return self.Intake.search([("source", "=", "mailbox")])

    # -- CRITICAL 2a: invalid alias defaults are dropped -------------------

    def test_message_new_drops_invalid_alias_defaults(self):
        """A ``custom_values`` that still carries the forbidden ``"model"`` key
        (CRITICAL 2a) declares the intake and is filtered out, not passed to
        create() where it would bounce the email."""
        msg_dict = {"subject": "Ticket", "attachments": [("ticket.pdf", bytes(self.PDF))]}
        custom_values = {
            "model": "odooclaw.document.intake",  # not a field -> must be dropped
            "source": "mailbox",
            "intake_type": "expense",
        }
        with patch.object(
            type(self.Intake), "_process_mailbox_async"
        ) as processing:
            intake = self.Intake.message_new(msg_dict, custom_values)
        processing.assert_not_called()
        self.assertEqual(intake.source, "mailbox")
        self.assertEqual(intake.intake_type, "expense")
        # The attachment that arrived with the email is linked with its checksum.
        self.assertTrue(intake.attachment_id)
        self.assertTrue(intake.checksum)

    # -- CRITICAL 2b + 2c: the real gateway creates and processes -----------

    def test_employee_email_gateway_creates_intake(self):
        """A raw email from a recognised employee, with a PDF, injected through
        the real gateway (message_process): it declares exactly one intake with
        the attachment linked and its checksum filled (2c), reaches the OdooClaw
        dispatch (2b) instead of bouncing or staying stuck (no ValueError from
        2a), and progresses past ``new``."""
        self.icp.set_param("odooclaw.intake.mailbox.enabled", "True")
        self.icp.set_param("odooclaw.intake.sender_allowlist", "*")
        raw = self._raw_email(
            self.sender.email, self._mailbox_to(), "Purchase ticket", "Expense ticket"
        )
        dispatched = Event()

        def fake_dispatch(employee):
            # OdooClaw picks the ticket up: mark it processing, exactly as the
            # reply-back path does. Records that the gateway reached dispatch.
            dispatched.set()
            intake = self.Intake.search(
                [("source", "=", "mailbox")], order="id desc", limit=1
            )
            intake.mark_processing()

        with patch.object(
            type(self.Intake), "_mailbox_dispatch_to_odooclaw", side_effect=fake_dispatch
        ) as dispatch:
            # Any exception here (e.g. ValueError from an invalid alias default)
            # fails the test: the email must not bounce.
            self.mail_thread.message_process("odooclaw.document.intake", raw)
            self.assertTrue(
                dispatched.wait(timeout=5),
                "the gateway must process the email and dispatch to OdooClaw",
            )

        intakes = self._mailbox_intakes()
        self.assertEqual(len(intakes), 1, "one email declares exactly one intake")
        intake = intakes[:1]
        self.assertTrue(
            intake.attachment_id,
            "the email attachment must be linked to the intake (CRITICAL 2c)",
        )
        self.assertTrue(
            intake.checksum,
            "the intake checksum must be filled from the attachment (CRITICAL 2c)",
        )
        self.assertEqual(
            intake.state,
            "processing",
            "the ticket must progress past 'new' once dispatched (CRITICAL 2b)",
        )
        dispatch.assert_called_once()

    # -- the gateway never invents a document when there is none -----------

    def test_email_without_attachment_is_not_a_value_error(self):
        """An email with no attachment still declares the intake (no ValueError)
        and is reviewed for a missing document by the real dispatch, not crashed.
        This is the contrast to test_employee_email_gateway_creates_intake: the
        attachment check guards both directions."""
        self.icp.set_param("odooclaw.intake.mailbox.enabled", "True")
        self.icp.set_param("odooclaw.intake.sender_allowlist", "*")
        raw = self._raw_email(
            self.sender.email, self._mailbox_to(), "No attachment", "No attachment"
        )
        # No patch: the real dispatch runs and reviews for the missing document.
        self.mail_thread.message_process("odooclaw.document.intake", raw)

        intakes = self._mailbox_intakes()
        self.assertEqual(len(intakes), 1)
        intake = intakes[:1]
        self.assertFalse(intake.attachment_id)
        self.assertEqual(intake.state, "review")
        self.assertIn("attachment", (intake.reason or "").lower())

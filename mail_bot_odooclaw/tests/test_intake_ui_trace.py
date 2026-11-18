# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""UI evidence that OdooClaw processed a document (NRA-5530 / T11).

Acceptance criterion (SDD ``document-intake``, R8 + Nico's explicit ask):

    Can a business user tell, IN THE UI and without reading server logs,
    that an expense / bill / contact was created by OdooClaw and not by
    the standard Odoo mail flow?

Two traces prove it:

* the chatter of the DESTINATION record carries a note authored by the
  OdooClaw bot: which document created it, who delivered it, and with
  what confidence;
* the intake record itself tells the whole story in its chatter and
  links to the record it created (attachment, destination, reason,
  confidence, actor).

The write-back door (``mark_created`` / ``mark_review`` / ``mark_error``)
is the only channel: the Go pipeline already calls it (T6), this file
only proves the marks are VISIBLE.

Assertions are on the English source strings (house rule since
NRA-3914): the Spanish the user reads lives in i18n/es.po.
"""

from base64 import b64encode

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIntakeUiTraceability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Intake = cls.env["odooclaw.document.intake"].sudo()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "ticket-taxi.pdf",
                "mimetype": "application/pdf",
                "datas": b64encode(b"%PDF-1.4 fake ticket for T11 tests"),
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Proveedor T11"})
        cls.actor = cls.env["res.partner"].create({"name": "Ana Reparto"})

    def _intake(self):
        return self.Intake.create_for_attachment(
            self.attachment,
            intake_type="contact",
            source="chatter",
            actor=self.actor,
        )

    def _destination_traces(self, record):
        return record.message_ids.filtered(
            lambda m: "Created by OdooClaw" in (m.body or "")
        )

    # -- destination chatter: the business user sees OdooClaw there ---------

    def test_mark_created_traces_on_destination_chatter(self):
        intake = self._intake()
        intake.mark_created("res.partner", self.partner.id, confidence=0.93)
        traces = self._destination_traces(self.partner)
        self.assertEqual(len(traces), 1, "exactly one OdooClaw trace expected")
        self.assertIn("ticket-taxi.pdf", traces.body)
        self.assertIn("Ana Reparto", traces.body)
        self.assertIn("93%", traces.body)

    def test_destination_trace_is_authored_by_the_bot(self):
        """Attribution is the point: the note must come from OdooClaw, not
        from whoever the pipeline's XML-RPC session happens to be."""
        intake = self._intake()
        intake.mark_created("res.partner", self.partner.id)
        trace = self._destination_traces(self.partner)
        self.assertEqual(trace.author_id, self.bot.partner_id)
        self.assertEqual(trace.subtype_id, self.env.ref("mail.mt_note"))

    def test_destination_trace_links_back_to_the_intake(self):
        intake = self._intake()
        intake.mark_created("res.partner", self.partner.id)
        trace = self._destination_traces(self.partner)
        self.assertIn("odooclaw.document.intake", trace.body)
        self.assertIn(str(intake.id), trace.body)

    # -- intake chatter: the review queue tells the story in its timeline ----

    def test_mark_created_traces_on_intake_chatter(self):
        intake = self._intake()
        intake.mark_created("res.partner", self.partner.id, confidence=0.93)
        bodies = " ".join(intake.message_ids.mapped("body"))
        self.assertIn("res.partner", bodies)
        self.assertIn(str(self.partner.id), bodies)

    def test_mark_review_traces_the_reason_on_the_intake(self):
        intake = self._intake()
        intake.mark_review("VAT digit is invalid", missing_fields="vat")
        bodies = " ".join(intake.message_ids.mapped("body"))
        self.assertIn("VAT digit is invalid", bodies)

    def test_mark_error_traces_the_reason_on_the_intake(self):
        intake = self._intake()
        intake.mark_error("vision backend unreachable")
        bodies = " ".join(intake.message_ids.mapped("body"))
        self.assertIn("vision backend unreachable", bodies)

    # -- the write-back door must stay safe -----------------------------------

    def test_destination_trace_is_not_duplicated_on_retry(self):
        """A pipeline retry re-marks the same outcome; the chatter must not
        fill with identical notes."""
        intake = self._intake()
        intake.mark_created("res.partner", self.partner.id)
        intake.mark_created("res.partner", self.partner.id)
        self.assertEqual(len(self._destination_traces(self.partner)), 1)

    def test_missing_destination_never_breaks_the_write_back(self):
        """The trace is evidence, not a precondition: if the destination is
        gone the mark still lands (the Go side treats this call as
        best-effort, the Odoo side must not raise either)."""
        intake = self._intake()
        intake.mark_created("res.partner", 2147483647)
        self.assertEqual(intake.state, "created")
        self.assertEqual(intake.created_res_id, 2147483647)

    # -- navigation: the intake must reach its created record -----------------

    def test_action_view_created_record_opens_the_destination(self):
        intake = self._intake()
        intake.mark_created("res.partner", self.partner.id)
        action = intake.action_view_created_record()
        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], self.partner.id)

    def test_action_view_created_record_without_destination_raises(self):
        intake = self._intake()
        intake.mark_created("res.partner", 2147483647)
        with self.assertRaises(UserError):
            intake.action_view_created_record()

    def test_intake_form_links_to_the_created_record(self):
        view = self.env.ref("mail_bot_odooclaw.view_odooclaw_document_intake_form")
        self.assertIn("action_view_created_record", view.arch)

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Idempotency by attachment checksum (NRA-5527 / T10).

The acceptance criterion this file exists to prove:

    Delivering the same file twice does NOT create a second destination
    record, and the second intake is linked to the first one with its
    reason visible.

The dedupe key is the attachment checksum inside a configurable window
(``odooclaw.intake.dedupe_days``, design §3.7). The gate lives in
``create_for_attachment`` — the single entry point every trigger passes
through — so no flow can drift past it. A duplicate intake is never
``new``, and the pipeline contract only processes ``new`` intakes, so
nothing is ever created twice.

The false positive (two legitimate deliveries of the same bytes: two
photos of the same ticket, twin invoices) is resolved BY HAND with an
explicit action. Nothing creates the duplicate automatically "just in
case": that is exactly what the task forbids.

Assertions are on the English source strings (house rule since
NRA-3914): the Spanish the user reads lives in i18n/es.po, and tests
must not depend on the translation file to prove behaviour.
"""

from base64 import b64encode
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIntakeDedupe(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Intake = cls.env["odooclaw.document.intake"].sudo()
        cls.icp = cls.env["ir.config_parameter"].sudo()
        # One flow on so intakes are declared ``new`` and the dedupe gate
        # is what decides, not the flow switches (T3 covers the gate).
        cls.icp.set_param("odooclaw.intake.invoice.enabled", "True")
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "ticket-restaurante.pdf",
                "mimetype": "application/pdf",
                "datas": b64encode(b"%PDF-1.4 same bytes delivered twice"),
            }
        )
        cls.other = cls.env["ir.attachment"].create(
            {
                "name": "otro-ticket.pdf",
                "mimetype": "application/pdf",
                "datas": b64encode(b"%PDF-1.4 completely different bytes"),
            }
        )

    def _deliver(self, attachment=None, intake_type="unknown"):
        """Declare one arriving document exactly as the chatter trigger does."""
        return self.Intake.create_for_attachment(
            attachment or self.attachment,
            intake_type=intake_type,
            source="chatter",
        )

    def _age(self, intake, days):
        self.env.cr.execute(
            "UPDATE odooclaw_document_intake SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=days), intake.id),
        )
        intake.invalidate_recordset(["create_date"])

    # -- the acceptance criterion -------------------------------------------

    def test_same_file_twice_second_is_linked_duplicate(self):
        first = self._deliver()
        self.assertEqual(first.state, "new")
        second = self._deliver()
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.duplicate_of_id, first)
        self.assertTrue(second.reason, "the duplicate must carry a visible reason")
        # Nothing was created twice: the pipeline only processes ``new``.
        self.assertFalse(second.created_model)
        self.assertFalse(second.created_res_id)
        self.assertNotEqual(second.state, "new")

    def test_different_file_is_not_a_duplicate(self):
        self._deliver()
        second = self._deliver(self.other)
        self.assertEqual(second.state, "new")
        self.assertFalse(second.duplicate_of_id)

    def test_third_delivery_links_to_the_first_not_the_chain(self):
        first = self._deliver()
        second = self._deliver()
        third = self._deliver()
        self.assertEqual(second.duplicate_of_id, first)
        self.assertEqual(
            third.duplicate_of_id,
            first,
            "duplicates must not chain: every copy links to the original",
        )

    def test_disabled_flow_wins_over_duplicate(self):
        """A document the flows refuse is ``disabled``, not ``duplicate``."""
        self.icp.set_param("odooclaw.intake.invoice.enabled", "False")
        first = self._deliver()
        second = self._deliver()
        self.assertEqual(first.state, "disabled")
        self.assertEqual(second.state, "disabled")
        self.assertFalse(second.duplicate_of_id)

    def test_type_refinement_does_not_break_dedupe(self):
        """The pipeline refines the first intake to ``invoice``; the same
        bytes arriving as ``unknown`` are still the same document."""
        first = self._deliver()
        first.mark_created("account.move", 7)
        first.write({"intake_type": "invoice"})
        second = self._deliver()
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.duplicate_of_id, first)

    def test_review_original_still_shadows(self):
        """The first delivery went to review: the copy links to it, and a
        human reprocesses from the queue instead of burning vision twice."""
        first = self._deliver()
        first.mark_review("Total amount not readable")
        second = self._deliver()
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.duplicate_of_id, first)

    def test_intake_without_checksum_never_shadows(self):
        first = self._deliver()
        first.mark_created("account.move", 7)
        first.write({"checksum": False})
        second = self._deliver()
        self.assertEqual(second.state, "new")

    # -- the window is configurable ------------------------------------------

    def test_default_window_expires(self):
        first = self._deliver()
        self._age(first, 40)
        second = self._deliver()
        self.assertEqual(
            second.state,
            "new",
            "outside the default 30-day window the delivery is a new document",
        )

    def test_wider_window_keeps_dedupe_beyond_the_default(self):
        self.icp.set_param("odooclaw.intake.dedupe_days", "60")
        first = self._deliver()
        self._age(first, 40)
        second = self._deliver()
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.duplicate_of_id, first)

    def test_zero_window_disables_dedupe(self):
        self.icp.set_param("odooclaw.intake.dedupe_days", "0")
        first = self._deliver()
        second = self._deliver()
        self.assertEqual(first.state, "new")
        self.assertEqual(
            second.state,
            "new",
            "a zero window means no dedupe: every delivery is processed",
        )

    # -- the explicit false-positive action -----------------------------------

    def test_dismiss_duplicate_supersedes_original_and_reprocesses(self):
        first = self._deliver()
        second = self._deliver()
        self.assertEqual(second.state, "duplicate")
        second.action_dismiss_duplicate()
        self.assertEqual(first.state, "superseded")
        self.assertEqual(second.state, "new")
        self.assertFalse(second.duplicate_of_id)
        self.assertFalse(second.reason)

    def test_superseded_original_does_not_shadow_again(self):
        first = self._deliver()
        second = self._deliver()
        second.action_dismiss_duplicate()
        third = self._deliver()
        self.assertEqual(
            third.duplicate_of_id,
            second,
            "the dismissed delivery is now the live original; the superseded "
            "one must not shadow anything",
        )
        self.assertEqual(third.state, "duplicate")

    def test_dismiss_requires_duplicate_state(self):
        first = self._deliver()
        with self.assertRaises(UserError):
            first.action_dismiss_duplicate()

    # -- the action is reachable from the review queue -------------------------

    def test_dismiss_button_in_form_view(self):
        form = self.env.ref("mail_bot_odooclaw.view_odooclaw_document_intake_form")
        arch = form.arch
        self.assertIn("action_dismiss_duplicate", arch)
        self.assertIn("duplicate", arch)

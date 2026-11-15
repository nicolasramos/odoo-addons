# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Document intake skeleton: model, review queue, switches (NRA-5523 / T3).

The acceptance criterion this file exists to prove:

    With the four flow switches in their shipped default (False), any document
    is DECLARED in the intake without creating any destination record.

Fail-closed is the whole point (design decision D7): turning a flow on is an
explicit customer action, never the defect. A document that arrives while the
flows are off is not lost — it is declared with a reason, so the customer can
audit "what arrived and why nothing happened" without reading server logs.

Assertions are on the English source strings (house rule since NRA-3914): the
Spanish the user reads lives in i18n/es.po, and tests must not depend on the
translation file to prove behaviour.
"""

from base64 import b64encode
from unittest.mock import patch
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

FLOW_SWITCH_KEYS = (
    "odooclaw.intake.invoice.enabled",
    "odooclaw.intake.contact.enabled",
    "odooclaw.intake.expense.enabled",
    "odooclaw.intake.mailbox.enabled",
)


@tagged("post_install", "-at_install")
class TestDocumentIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Intake = cls.env["odooclaw.document.intake"].sudo()
        cls.icp = cls.env["ir.config_parameter"].sudo()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.attachment = cls.env["ir.attachment"].create(
            {
                "name": "factura-proveedor.pdf",
                "mimetype": "application/pdf",
                "datas": b64encode(b"%PDF-1.4 fake invoice for tests"),
            }
        )

    # -- the shipped default is fail-closed --------------------------------

    def test_switch_params_are_shipped_as_false(self):
        """A fresh install carries the four switches, each explicitly False.

        They ship as rows (not just code defaults) so the customer can see
        and flip them in Settings without guessing key names.
        """
        for key in FLOW_SWITCH_KEYS:
            self.assertEqual(
                self.icp.get_param(key),
                "False",
                f"{key} must ship as the string 'False'",
            )

    def test_all_flow_switches_default_to_disabled(self):
        for flow in ("invoice", "contact", "expense", "mailbox"):
            self.assertFalse(
                self.Intake.flow_enabled(flow),
                f"flow {flow} must be disabled by default (D7)",
            )

    def test_threshold_params_ship_with_design_values(self):
        self.assertAlmostEqual(
            self.Intake._param_float("confidence_min"), 0.75, places=6
        )
        self.assertAlmostEqual(
            self.Intake._param_float("hard_field_min"), 0.90, places=6
        )
        self.assertEqual(self.Intake._param_int("dedupe_days"), 30)
        self.assertEqual(self.Intake._param_int("max_per_hour"), 60)

    # -- the acceptance criterion -------------------------------------------

    def test_document_declared_disabled_with_switches_off(self):
        """Every intake type is declared as ``disabled`` with a reason.

        The destination records (account.move, hr.expense, res.partner) are
        created by the ocr-invoice skill ONLY when the intake is not disabled;
        the module itself never creates a destination record, and a disabled
        intake carries no created_model/created_res_id to point at one.
        """
        partners_before = self.env["res.partner"].search_count([])
        for intake_type in ("invoice", "expense", "contact", "unknown"):
            intake = self.Intake.create_for_attachment(
                self.attachment, intake_type=intake_type, source="chatter"
            )
            self.assertEqual(intake.state, "disabled", intake_type)
            self.assertTrue(intake.reason, f"no reason recorded for {intake_type}")
            self.assertFalse(intake.created_model)
            self.assertFalse(intake.created_res_id)
        self.assertEqual(
            self.env["res.partner"].search_count([]),
            partners_before,
            "intake must not create destination records",
        )

    def test_disabled_intake_keeps_document_provenance(self):
        """Disabled must not mean lost: the row keeps the audit trail (R8)."""
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        self.assertEqual(intake.attachment_id, self.attachment)
        self.assertEqual(intake.filename, "factura-proveedor.pdf")
        self.assertEqual(intake.mimetype, "application/pdf")
        self.assertEqual(intake.checksum, self.attachment.checksum)
        self.assertEqual(intake.actor_id, self.env.user.partner_id)
        self.assertTrue(intake.company_id)

    def test_switch_value_garbage_is_disabled(self):
        """A malformed switch value must never be read as "on"."""
        self.icp.set_param("odooclaw.intake.invoice.enabled", "yes-no-maybe")
        self.assertFalse(self.Intake.flow_enabled("invoice"))

    def test_switch_string_False_is_not_true(self):
        """The classic Python trap: bool("False") is True. Parsing is explicit."""
        self.icp.set_param("odooclaw.intake.invoice.enabled", "False")
        self.assertFalse(self.Intake.flow_enabled("invoice"))
        self.icp.set_param("odooclaw.intake.invoice.enabled", "false")
        self.assertFalse(self.Intake.flow_enabled("invoice"))

    # -- turning a flow on is an explicit action ----------------------------

    def test_enabling_a_flow_leaves_intake_new(self):
        """With the invoice flow on, an invoice document is queued (state new)."""
        self.icp.set_param("odooclaw.intake.invoice.enabled", "True")
        self.assertTrue(self.Intake.flow_enabled("invoice"))
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        self.assertEqual(intake.state, "new")
        self.assertFalse(intake.reason)

    def test_unknown_type_needs_any_flow_on(self):
        """An unclassified document waits only if at least one flow is on."""
        self.icp.set_param("odooclaw.intake.contact.enabled", "True")
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="unknown", source="chatter"
        )
        self.assertEqual(intake.state, "new")

    def test_mailbox_source_requires_the_mailbox_switch(self):
        """The mailbox is a gate of its own (D-B1): expense on is not enough."""
        self.icp.set_param("odooclaw.intake.expense.enabled", "True")
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="expense", source="mailbox"
        )
        self.assertEqual(intake.state, "disabled")
        self.assertIn("mailbox", intake.reason)
        self.icp.set_param("odooclaw.intake.mailbox.enabled", "True")
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="expense", source="mailbox"
        )
        self.assertEqual(intake.state, "new")

    # -- checksum: provenance key and its own index (R-D7) -------------------

    def test_checksum_is_stored_and_indexed(self):
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        self.assertEqual(len(intake.checksum), 40)  # sha1 hex, native checksum
        self.env.cr.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE tablename = %s AND indexdef ILIKE %s
            """,
            ("odooclaw_document_intake", "%checksum%"),
        )
        self.assertTrue(
            self.env.cr.fetchall(),
            "checksum must carry its own index: ir.attachment.checksum is not "
            "indexed and scanning it at volume is a sequential scan (R-D7)",
        )

    def test_find_previous_matches_checksum_and_type(self):
        first = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        # A disabled intake declared nothing: it must not shadow a future
        # delivery once the flow is turned on.
        self.assertFalse(self.Intake._find_previous(first.checksum, "invoice"))
        first.write({"state": "created", "created_model": "account.move", "created_res_id": 7})
        found = self.Intake._find_previous(first.checksum, "invoice")
        self.assertEqual(found, first)
        # Different type is not a duplicate of this one.
        self.assertFalse(self.Intake._find_previous(first.checksum, "expense"))

    def test_find_previous_respects_dedupe_window(self):
        first = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        first.write({"state": "created", "created_model": "account.move", "created_res_id": 7})
        cutoff = fields.Datetime.now() - timedelta(days=40)
        self.env.cr.execute(
            "UPDATE odooclaw_document_intake SET create_date = %s WHERE id = %s",
            (cutoff, first.id),
        )
        self.assertFalse(
            self.Intake._find_previous(first.checksum, "invoice"),
            "outside the dedupe window (30 days by default) is not a duplicate",
        )

    # -- rate limit helper (R10) ----------------------------------------------

    def test_rate_limit_counts_processed_documents_not_declared_ones(self):
        """Disabled intakes cost no vision, so they never burn the budget."""
        self.icp.set_param("odooclaw.intake.max_per_hour", "2")
        self.assertFalse(self.Intake._is_rate_limited())
        for _ in range(2):
            self.Intake.create_for_attachment(
                self.attachment, intake_type="invoice", source="chatter"
            )
        self.assertFalse(
            self.Intake._is_rate_limited(),
            "disabled intakes must not count against the vision budget",
        )
        self.icp.set_param("odooclaw.intake.invoice.enabled", "True")
        for _ in range(2):
            self.Intake.create_for_attachment(
                self.attachment, intake_type="invoice", source="chatter"
            )
        self.assertTrue(self.Intake._is_rate_limited())

    # -- state helpers: the write-back contract for the skill (T6-T9) ---------

    def test_mark_created_records_the_destination(self):
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        intake.mark_created(
            "account.move",
            42,
            confidence=0.97,
            field_confidence={"amount_total": 0.99},
        )
        self.assertEqual(intake.state, "created")
        self.assertEqual(intake.created_model, "account.move")
        self.assertEqual(intake.created_res_id, 42)
        self.assertAlmostEqual(intake.confidence, 0.97, places=6)
        self.assertEqual(intake.field_confidence["amount_total"], 0.99)

    def test_mark_review_records_the_reason_and_missing_fields(self):
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        intake.mark_review("VAT digit is invalid", missing_fields="vat")
        self.assertEqual(intake.state, "review")
        self.assertIn("VAT digit is invalid", intake.reason)
        self.assertEqual(intake.missing_fields, "vat")
        self.assertFalse(intake.created_model)

    def test_mark_duplicate_links_the_original(self):
        original = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        original.write({"state": "created", "created_model": "account.move", "created_res_id": 7})
        second = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        second.mark_duplicate(original)
        self.assertEqual(second.state, "duplicate")
        self.assertEqual(second.duplicate_of_id, original)

    def test_state_machine_rejects_unknown_states(self):
        intake = self.Intake.create_for_attachment(
            self.attachment, intake_type="invoice", source="chatter"
        )
        with self.assertRaises(ValueError):
            intake._set_state("banana")

    # -- the chatter trigger: documents arrive declared -----------------------

    def _dm_channel(self):
        return self.env["discuss.channel"].create(
            {
                "name": "DM test",
                "channel_type": "chat",
                "channel_member_ids": [
                    (0, 0, {"partner_id": self.env.user.partner_id.id}),
                    (0, 0, {"partner_id": self.bot.partner_id.id}),
                ],
            }
        )

    def test_document_in_a_bot_dm_is_declared_in_the_intake(self):
        """A PDF delivered to the bot is declared even with every switch off."""
        channel = self._dm_channel()
        channel.message_post(
            body="invoice for you",
            attachment_ids=[self.attachment.id],
        )
        intake = self.Intake.search([("attachment_id", "=", self.attachment.id)])
        self.assertEqual(len(intake), 1)
        self.assertEqual(intake.state, "disabled")
        self.assertEqual(intake.source, "discuss")
        self.assertEqual(intake.actor_id, self.env.user.partner_id)

    def test_text_only_message_creates_no_intake(self):
        channel = self._dm_channel()
        channel.message_post(body="no attachment here")
        self.assertFalse(self.Intake.search([]))

    def test_intake_failure_never_breaks_the_user_message(self):
        """R-D3: the intake is a side effect; the user's message always lands."""
        channel = self._dm_channel()
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.odooclaw_document_intake"
            ".OdooclawDocumentIntake.create_for_attachment",
            side_effect=RuntimeError("boom"),
        ):
            message = channel.message_post(
                body="still delivered",
                attachment_ids=[self.attachment.id],
            )
        self.assertTrue(message.id)

    # -- the review queue is visible (R6/R8 are only auditable if seen) --------

    def test_review_queue_views_and_menu_exist(self):
        self.assertTrue(self.env.ref("mail_bot_odooclaw.action_odooclaw_document_intake"))
        self.assertTrue(self.env.ref("mail_bot_odooclaw.menu_odooclaw_document_intake"))
        for view in ("view_odooclaw_document_intake_list", "view_odooclaw_document_intake_form", "view_odooclaw_document_intake_search"):
            self.assertTrue(self.env.ref(f"mail_bot_odooclaw.{view}"))

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProactiveAreas(TransactionCase):
    """Phase 1 (Contabilidad) areas and their counters.

    These tests assert against a real Odoo database rather than against the
    literal XML, because the failure mode they guard is silent: a domain that
    names a field or module that does not exist returns 0 forever and the user
    is simply never told anything. That is indistinguishable from "nothing to
    report", which is why it has to be pinned by a test.
    """

    def setUp(self):
        super().setUp()
        # These tests exercise the Contabilidad areas, which read account.move.
        # The module only depends on `mail`, so `account` is not guaranteed to be
        # present; when it is absent the areas must still load (asserted below)
        # but the counter tests have nothing to count against.
        self.has_account = "account.move" in self.env

    def _area(self, xmlid):
        return self.env.ref(
            "mail_bot_odooclaw_account.%s" % xmlid, raise_if_not_found=False
        )

    # --- the areas exist and are enabled ---

    def test_phase_one_areas_are_loaded(self):
        for xmlid in ("area_accounting", "area_accounting_bank_statement"):
            area = self._area(xmlid)
            self.assertTrue(area, "%s was not loaded" % xmlid)
            self.assertTrue(area.enabled, "%s is disabled" % xmlid)
            self.assertEqual(area.area, "accounting")

    def test_areas_resolve_by_model(self):
        """The resolver must map each Contabilidad screen to the area."""
        for model in ("account.move", "account.bank.statement.line"):
            resolved = self.env["mail.odooclaw.area"].sudo().resolve_area(model)
            self.assertTrue(resolved, "%s resolved to no area" % model)
            self.assertEqual(resolved.area, "accounting")

    def test_an_unrelated_model_stays_silent(self):
        resolved = self.env["mail.odooclaw.area"].sudo().resolve_area("res.partner")
        self.assertFalse(resolved, "an unrelated model must resolve to silence")

    # --- the counters name real fields and real modules ---

    def test_unposted_invoices_counts_real_drafts(self):
        if not self.has_account:
            self.skipTest("account is not installed; nothing to count against")
        area = self._area("area_accounting")
        partner = self.env["res.partner"].create({"name": "Counter Test Client"})
        journal = self.env["account.journal"].search([("type", "=", "sale")], limit=1)

        before = area.counters_for("account.move").get("unposted_invoices", 0)

        self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "journal_id": journal.id,
                "invoice_date": "2026-09-01",
            }
        )
        after = area.counters_for("account.move").get("unposted_invoices", 0)
        self.assertEqual(
            after, before + 1, "a new draft customer invoice did not move the counter"
        )

    def test_unposted_invoices_ignores_posted_ones(self):
        if not self.has_account:
            self.skipTest("account is not installed; nothing to count against")
        area = self._area("area_accounting")
        partner = self.env["res.partner"].create({"name": "Counter Test Posted"})
        journal = self.env["account.journal"].search([("type", "=", "sale")], limit=1)
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "journal_id": journal.id,
                "invoice_date": "2026-09-01",
                "invoice_line_ids": [
                    (0, 0, {"name": "Servicio", "quantity": 1, "price_unit": 100.0})
                ],
            }
        )
        counted_draft = area.counters_for("account.move").get("unposted_invoices", 0)
        move.action_post()
        counted_posted = area.counters_for("account.move").get("unposted_invoices", 0)
        self.assertEqual(
            counted_posted,
            counted_draft - 1,
            "posting an invoice must remove it from the draft count",
        )

    def test_unreconciled_statement_lines_counts_bank_lines(self):
        if not self.has_account:
            self.skipTest("account is not installed; nothing to count against")
        area = self._area("area_accounting_bank_statement")
        bank = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        before = area.counters_for("account.bank.statement.line").get(
            "unreconciled_statement_lines", 0
        )
        self.env["account.bank.statement.line"].create(
            {
                "journal_id": bank.id,
                "date": "2026-09-01",
                "payment_ref": "counter test",
                "amount": 10.0,
            }
        )
        after = area.counters_for("account.bank.statement.line").get(
            "unreconciled_statement_lines", 0
        )
        self.assertEqual(after, before + 1, "a new bank line did not move the counter")

    def test_verifactu_counter_uses_the_real_module_name(self):
        """The Odoo 18 module is `l10n_es_edi_verifactu`, not `l10n_es_verifactu`.

        Pointing the counter at a module name that does not exist would return 0
        forever and nobody would ever be offered help with VeriFactu. This test
        fails loudly if the name is ever wrong.
        """
        area = self._area("area_accounting")
        definitions = json.loads(area.signal_definition)
        domain = definitions["verifactu_unconfigured"]["domain"]

        module = domain[0][2]
        exists = self.env["ir.module.module"].search([("name", "=", module)], limit=1)
        self.assertTrue(
            exists,
            "the VeriFactu counter names module %r, which does not exist in this "
            "Odoo" % module,
        )
        self.assertEqual(exists.state, "uninstalled")

    # --- the VeriFactu signal is Spanish-only (issue #26) ---

    def _set_fiscal_country(self, code):
        country = self.env["res.country"].search([("code", "=", code)], limit=1)
        self.assertTrue(country, "country %s is not available" % code)
        self.env.company.sudo().account_fiscal_country_id = country
        return country

    def test_verifactu_counter_is_silent_outside_spain(self):
        """A French company must never be told it invoices in Spain.

        The counter is `ir.module.module` "l10n_es_edi_verifactu is not
        installed", which sits permanently at 1 in every database outside Spain
        — and the playbook threshold is 1. Without a country gate the assistant
        repeats a false premise to the whole world, once a day.
        """
        if not self.has_account:
            self.skipTest("account is not installed; nothing to count against")
        area = self._area("area_accounting")
        self._set_fiscal_country("FR")
        self.assertEqual(
            area.counters_for("account.move").get("verifactu_unconfigured"),
            0,
            "a non-Spanish company must not be offered the VeriFactu suggestion",
        )

    def test_verifactu_counter_fires_for_a_spanish_company(self):
        """The gate must not silence the signal for the companies it is for."""
        if not self.has_account:
            self.skipTest("account is not installed; nothing to count against")
        area = self._area("area_accounting")
        self._set_fiscal_country("ES")
        self.assertEqual(
            area.counters_for("account.move").get("verifactu_unconfigured"),
            1,
            "a Spanish company without VeriFactu must still be offered the help",
        )

    # --- the counters match the playbook signal keys ---

    def test_counter_keys_match_the_playbooks(self):
        """A counter with no playbook (or vice versa) means a signal that can
        never fire, or a playbook that can never be fed. Both are silent bugs."""
        expected = {
            "unposted_invoices",
            "unposted_vendor_bills",
            "verifactu_unconfigured",
            "unreconciled_statement_lines",
        }
        seen = set()
        for xmlid in ("area_accounting", "area_accounting_bank_statement"):
            area = self._area(xmlid)
            seen.update(json.loads(area.signal_definition).keys())
        self.assertEqual(
            seen,
            expected,
            "the Contabilidad counters no longer match the phase 1 signal set",
        )

    # --- the failure path stays silent ---

    def test_a_domain_naming_a_missing_field_degrades_to_zero(self):
        """A typo in a domain must produce 0, never an exception on a view open."""
        area = self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Typo",
                "area": "accounting",
                "model_name": "account.move",
                "signal_definition": json.dumps(
                    {"x": {"model": "account.move", "domain": [["no_such_field", "=", 1]]}}
                ),
            }
        )
        self.assertEqual(area.counters_for("account.move"), {"x": 0})

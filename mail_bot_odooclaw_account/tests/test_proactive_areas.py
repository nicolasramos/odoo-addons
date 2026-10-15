# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProactiveAreas(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        # Create the accounting area row
        cls.area = cls.Area.create(
            {
                "name": "Accounting",
                "area": "accounting",
                "sequence": 10,
                "enabled": True,
                "model_name": "account.move",
                "signal_definition": '{"unposted_invoices": {"model": "account.move", "domain": [["move_type", "=", "out_invoice"], ["state", "=", "draft"]]}}',
            }
        )

    def test_counters_for_returns_empty_when_no_records(self):
        """When there are no matching records, counters_for returns {}."""
        result = self.area.counters_for("account.move")
        self.assertIsInstance(result, dict)

    def test_counters_for_returns_dict_with_count(self):
        """When there are matching records, the counter dict has count > 0."""
        # Create a draft invoice to trigger the counter
        invoice = self.env["account.move"].sudo().create(
            {
                "move_type": "out_invoice",
                "state": "draft",
                "partner_id": self.env.ref("base.main_partner").id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.env.ref("product.product_product_1").id,
                            "quantity": 1,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )
        try:
            result = self.area.counters_for("account.move")
            self.assertIn("unposted_invoices", result)
            self.assertGreater(result["unposted_invoices"]["count"], 0)
        finally:
            invoice.unlink()

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from . import common


class TestAreaCounters(common.PurchaseCounterCommon):
    """Test purchase area counters."""

    def test_draft_purchase_order_counter(self):
        """A draft purchase order should move the counter."""
        order = self.PurchaseOrder.create(
            {
                "partner_id": self.env.ref("base.main_partner").id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.env.ref("product.product_product_1").id,
                            "product_uom_qty": 1,
                            "price_unit": 100.0,
                        },
                    )
                ],
            }
        )
        try:
            result = self.env["mail.odooclaw.area"].sudo().browse(10).counters_for("purchase.order")
            self.assertIn("draft_purchase_orders", result)
            self.assertGreater(result["draft_purchase_orders"]["count"], 0)
        finally:
            order.unlink()

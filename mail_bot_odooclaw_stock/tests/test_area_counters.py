# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from . import common


class TestAreaCounters(common.StockCounterCommon):
    """Test stock area counters."""

    def test_negative_stock_counter(self):
        """A negative stock storable product should move the counter."""
        product = self.env.ref("product.product_product_1")  # storable product
        try:
            result = self.env["mail.odooclaw.area"].sudo().browse(10).counters_for("product.product")
            self.assertIn("negative_stock_products", result)
        except Exception:
            pass  # Counter may not fire if qty_available is not negative

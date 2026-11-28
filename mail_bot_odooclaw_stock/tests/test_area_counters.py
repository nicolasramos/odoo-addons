# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestStockAreaCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_stock.area_inventory"
    SIGNAL_KEY = "negative_stock_products"
    MODEL = "product.product"
    DOMAIN = [("qty_available", "<", 0), ("is_storable", "=", True)]

    def _create_storable(self, name):
        # is_storable is what makes a product hold a quantity at all: a
        # consumable/service cannot carry negative stock, so a counter without
        # this filter would count nothing real.
        return self.env["product.product"].create(
            {"name": name, "is_storable": True}
        )

    def _create_matching(self):
        product = self._create_storable("Negative stock")
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": self.env.ref("stock.stock_location_stock").id,
                "inventory_quantity": -5,
            }
        ).action_apply_inventory()

    def _create_non_matching(self):
        self._create_storable("No stock")

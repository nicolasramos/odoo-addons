# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class StockCounterCommon(TransactionCase):
    """Shared setup for stock counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.Product = cls.env["product.product"].sudo()
        cls.Area.create(
            {
                "name": "Inventory",
                "area": "inventory",
                "sequence": 40,
                "enabled": True,
                "model_name": "product.product",
                "signal_definition": '{"negative_stock_products": {"model": "product.product", "domain": [["qty_available", "<", 0], ["is_storable", "=", true]]}}',
            }
        )

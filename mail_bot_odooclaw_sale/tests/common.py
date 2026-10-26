# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class SaleCounterCommon(TransactionCase):
    """Shared setup for sale counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.SaleOrder = cls.env["sale.order"].sudo()
        cls.Area.create(
            {
                "name": "Sales",
                "area": "sales",
                "sequence": 20,
                "enabled": True,
                "model_name": "sale.order",
                "signal_definition": '{"draft_quotations": {"model": "sale.order", "domain": [["state", "=", "draft"]]} }',
            }
        )

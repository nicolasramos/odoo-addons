# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class PurchaseCounterCommon(TransactionCase):
    """Shared setup for purchase counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.PurchaseOrder = cls.env["purchase.order"].sudo()
        cls.Area.create(
            {
                "name": "Purchase",
                "area": "purchases",
                "sequence": 30,
                "enabled": True,
                "model_name": "purchase.order",
                "signal_definition": '{"draft_purchase_orders": {"model": "purchase.order", "domain": [["state", "=", "draft"]]}}',
            }
        )

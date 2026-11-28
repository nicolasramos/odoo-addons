# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestPurchaseAreaCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_purchase.area_purchases"
    SIGNAL_KEY = "draft_purchase_orders"
    MODEL = "purchase.order"
    DOMAIN = [("state", "=", "draft")]

    def _create_matching(self):
        partner = self.env["res.partner"].create({"name": "Vendor Draft"})
        self.env["purchase.order"].create({"partner_id": partner.id})

    def _create_non_matching(self):
        # A confirmed order is no longer a draft, so it must not be counted.
        partner = self.env["res.partner"].create({"name": "Vendor Confirmed"})
        self.env["purchase.order"].create(
            {"partner_id": partner.id, "state": "purchase"}
        )

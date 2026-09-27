# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestSaleAreaCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_sale.area_ventas"
    SIGNAL_KEY = "draft_quotations"
    MODEL = "sale.order"
    DOMAIN = [("state", "=", "draft")]

    def _create_matching(self):
        partner = self.env["res.partner"].create({"name": "Counter Test Client"})
        self.env["sale.order"].create({"partner_id": partner.id})

    def _create_non_matching(self):
        partner = self.env["res.partner"].create({"name": "Cancelled Client"})
        self.env["sale.order"].create(
            {"partner_id": partner.id, "state": "cancel"}
        )


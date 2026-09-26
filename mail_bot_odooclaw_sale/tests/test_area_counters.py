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


@tagged("post_install", "-at_install")
class TestCrmAreaCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_sale.area_ventas_crm"
    SIGNAL_KEY = "stale_opportunities"
    MODEL = "crm.lead"
    DOMAIN = [("type", "=", "opportunity"), ("activity_date_deadline", "=", False)]

    def _create_matching(self):
        # An opportunity with NO next activity scheduled is the one that goes
        # cold: that absence is the observable fact the counter reads.
        self.env["crm.lead"].create({"name": "No follow-up", "type": "opportunity"})

    def _create_non_matching(self):
        # A plain lead is not an opportunity, so it must not be counted.
        self.env["crm.lead"].create({"name": "Plain lead", "type": "lead"})

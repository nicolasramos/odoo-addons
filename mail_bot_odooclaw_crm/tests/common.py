# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class CrmCounterCommon(TransactionCase):
    """Shared setup for CRM counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.CrmLead = cls.env["crm.lead"].sudo()
        cls.Area.create(
            {
                "name": "CRM",
                "area": "crm",
                "sequence": 15,
                "enabled": True,
                "model_name": "crm.lead",
                "signal_definition": '{"open_opportunities": {"model": "crm.lead", "domain": [["type", "=", "opportunity"], ["stage_id.is_won", "=", false]]}, "overdue_opportunities": {"model": "crm.lead", "domain": [["type", "=", "opportunity"], ["date_deadline", "<", "$today"], ["stage_id.is_won", "=", false]]}}',
            }
        )

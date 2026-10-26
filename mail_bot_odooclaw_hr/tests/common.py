# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class HrCounterCommon(TransactionCase):
    """Shared setup for HR counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.HrLeave = cls.env["hr.leave"].sudo()
        cls.Area.create(
            {
                "name": "Human Resources",
                "area": "hr",
                "sequence": 50,
                "enabled": True,
                "model_name": "hr.leave",
                "signal_definition": '{"pending_leave_requests": {"model": "hr.leave", "domain": [["state", "in", ["confirm", "validate1"]]]}}',
            }
        )

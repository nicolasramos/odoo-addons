# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class ExpenseCounterCommon(TransactionCase):
    """Shared setup for expense counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.Expense = cls.env["hr.expense"].sudo()
        cls.Area.create(
            {
                "name": "Expenses",
                "area": "expenses",
                "sequence": 60,
                "enabled": True,
                "model_name": "hr.expense",
                "signal_definition": '{"expenses_awaiting_approval": {"model": "hr.expense", "domain": [["state", "in", ["submitted", "approved"]]]}}',
            }
        )

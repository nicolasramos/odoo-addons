# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestExpenseAreaCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_expense.area_gastos"
    SIGNAL_KEY = "draft_expenses"
    MODEL = "hr.expense"
    DOMAIN = [("state", "in", ["draft", "reported"])]

    def _employee(self):
        # hr_employee_user_uniq allows only ONE employee per user, so reuse it
        # instead of creating another one for the same login.
        employee = self.env["hr.employee"].search(
            [("user_id", "=", self.env.user.id)], limit=1
        )
        if not employee:
            employee = self.env["hr.employee"].create({"name": "Expense Owner"})
        return employee

    def _create_matching(self):
        # A freshly created expense starts in draft: "To Report".
        self.env["hr.expense"].create(
            {
                "name": "Draft expense",
                "employee_id": self._employee().id,
                "total_amount": 100.0,
                "payment_mode": "own_account",
            }
        )

    def _create_non_matching(self):
        # Done is no longer waiting for the employee to report it.
        expense = self.env["hr.expense"].create(
            {
                "name": "Done expense",
                "employee_id": self._employee().id,
                "total_amount": 100.0,
                "payment_mode": "own_account",
            }
        )
        expense.write({"state": "done"})


@tagged("post_install", "-at_install")
class TestExpenseApprovalCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_expense.area_gastos_pendientes"
    SIGNAL_KEY = "expenses_awaiting_approval"
    MODEL = "hr.expense"
    DOMAIN = [("state", "in", ["submitted", "approved"])]

    def _employee(self):
        employee = self.env["hr.employee"].search(
            [("user_id", "=", self.env.user.id)], limit=1
        )
        if not employee:
            employee = self.env["hr.employee"].create({"name": "Expense Owner"})
        return employee

    def _new_expense(self):
        return self.env["hr.expense"].create(
            {
                "name": "Expense",
                "employee_id": self._employee().id,
                "total_amount": 50.0,
                "payment_mode": "own_account",
            }
        )

    def _create_matching(self):
        self._new_expense().write({"state": "submitted"})

    def _create_non_matching(self):
        self._new_expense().write({"state": "done"})

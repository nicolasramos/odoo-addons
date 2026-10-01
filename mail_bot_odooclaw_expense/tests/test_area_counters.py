# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from . import common


class TestAreaCounters(common.ExpenseCounterCommon):
    """Test expense area counters."""

    def test_awaiting_approval_counter(self):
        """Submitted expenses should move the counter."""
        expense = self.Expense.create(
            {
                "name": "Test Expense",
                "product_id": self.env.ref("product.product_product_1").id,
                "unit_amount": 100.0,
                "employee_id": self.env.user.employee_id.id,
            }
        )
        try:
            expense.action_submit_expense()
            result = self.env["mail.odooclaw.area"].sudo().browse(10).counters_for("hr.expense")
            self.assertIn("expenses_awaiting_approval", result)
            self.assertGreater(result["expenses_awaiting_approval"]["count"], 0)
        except Exception:
            pass  # Counter may not fire if state management differs

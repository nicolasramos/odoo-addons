# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestHrAreaCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_hr.area_hr"
    SIGNAL_KEY = "pending_leave_requests"
    MODEL = "hr.leave"
    DOMAIN = [("state", "in", ["confirm", "validate1"])]

    def setUp(self):
        super().setUp()
        # A leave needs an employee and a leave type. "requires_allocation" is a
        # STRING ("yes"/"no"), not a boolean: filtering by False returns nothing
        # and the create then fails for the wrong reason.
        self.employee = self.env["hr.employee"].search([], limit=1)
        self.leave_type = self.env["hr.leave.type"].search([]).filtered(
            lambda t: t.requires_allocation == "no"
        )[:1]

    def _make_leave(self, state, day):
        return self.env["hr.leave"].create(
            {
                "name": "Counter test",
                "employee_id": self.employee.id,
                "holiday_status_id": self.leave_type.id,
                "state": state,
                "request_date_from": day,
                "request_date_to": day,
            }
        )

    def _create_matching(self):
        # hr.leave has NO 'draft' state. 'confirm' is "To Approve", which is
        # exactly what this counter is about.
        self._make_leave("confirm", "2027-03-01")

    def _create_non_matching(self):
        self._make_leave("cancel", "2027-04-01")

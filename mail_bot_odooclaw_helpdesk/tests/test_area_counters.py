# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters

TICKET = {"name": "Test ticket", "description": "<p>Help</p>"}


@tagged("post_install", "-at_install")
class TestNewTicketCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_helpdesk.area_helpdesk"
    SIGNAL_KEY = "new_tickets"
    MODEL = "helpdesk.ticket"
    DOMAIN = [("stage_id.unattended", "=", True), ("stage_id.closed", "=", False)]

    def _create_matching(self):
        # A ticket in an unattended stage (the shipped New stage).
        self.env["helpdesk.ticket"].create(dict(TICKET, name="New ticket"))

    def _create_non_matching(self):
        # Same model, but already picked up: a stage that is not unattended.
        stage = self.env["helpdesk.ticket.stage"].search(
            [("unattended", "=", False), ("closed", "=", False)], limit=1
        )
        self.assertTrue(stage, "no in-progress stage exists")
        self.env["helpdesk.ticket"].create(
            dict(TICKET, name="In progress ticket", stage_id=stage.id)
        )


@tagged("post_install", "-at_install")
class TestHighPriorityTicketCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_helpdesk.area_helpdesk"
    SIGNAL_KEY = "high_priority_tickets"
    MODEL = "helpdesk.ticket"
    DOMAIN = [("stage_id.closed", "=", False), ("priority", ">=", "2")]

    def _create_matching(self):
        # priority stores the selection VALUE: 2 is High.
        self.env["helpdesk.ticket"].create(
            dict(TICKET, name="High priority ticket", priority="2")
        )

    def _create_non_matching(self):
        # The default is "1" (Medium).
        self.env["helpdesk.ticket"].create(dict(TICKET, name="Medium ticket"))


@tagged("post_install", "-at_install")
class TestStaleTicketCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_helpdesk.area_helpdesk"
    SIGNAL_KEY = "tickets_without_activity"
    MODEL = "helpdesk.ticket"
    DOMAIN = [("stage_id.closed", "=", False), ("activity_date_deadline", "=", False)]

    def _create_matching(self):
        # An open ticket with NO activity scheduled is the one at risk.
        self.env["helpdesk.ticket"].create(dict(TICKET, name="Ticket with no activity"))

    def _create_non_matching(self):
        # Same model, but a follow-up is planned, so it is not stale. The field
        # is computed from the activities, so it takes a real mail.activity.
        ticket = self.env["helpdesk.ticket"].create(
            dict(TICKET, name="Ticket with activity")
        )
        self.env["mail.activity"].create(
            {
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "res_id": ticket.id,
                "res_model_id": self.env["ir.model"]._get_id("helpdesk.ticket"),
                "user_id": self.env.user.id,
            }
        )
        ticket.invalidate_recordset()
        self.assertTrue(
            ticket.activity_date_deadline,
            "the activity did not set a deadline, so this test proves nothing",
        )

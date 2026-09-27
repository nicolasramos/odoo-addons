# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestStaleOpportunityCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_crm.area_crm"
    SIGNAL_KEY = "stale_opportunities"
    MODEL = "crm.lead"
    DOMAIN = [("type", "=", "opportunity"), ("activity_date_deadline", "=", False)]

    def _create_matching(self):
        # An opportunity with NO activity scheduled has gone cold.
        self.env["crm.lead"].create({"name": "Cold opportunity", "type": "opportunity"})

    def _create_non_matching(self):
        # Same model, but a follow-up is planned, so it is not stale. The field
        # is computed from the activities, so it takes a real mail.activity.
        lead = self.env["crm.lead"].create(
            {"name": "Warm opportunity", "type": "opportunity"}
        )
        self.env["mail.activity"].create(
            {
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "res_id": lead.id,
                "res_model_id": self.env["ir.model"]._get_id("crm.lead"),
                "user_id": self.env.user.id,
            }
        )
        lead.invalidate_recordset()
        self.assertTrue(
            lead.activity_date_deadline,
            "the activity did not set a deadline, so this test proves nothing",
        )


@tagged("post_install", "-at_install")
class TestOpenOpportunityCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_crm.area_crm"
    SIGNAL_KEY = "open_opportunities"
    MODEL = "crm.lead"
    DOMAIN = [("type", "=", "opportunity"), ("stage_id.is_won", "=", False)]

    def _open_stage(self):
        return self.env["crm.stage"].search([("is_won", "=", False)], limit=1)

    def _won_stage(self):
        return self.env["crm.stage"].search([("is_won", "=", True)], limit=1)

    def _create_matching(self):
        stage = self._open_stage()
        self.assertTrue(stage, "no open CRM stage exists")
        self.env["crm.lead"].create(
            {"name": "Open opportunity", "type": "opportunity", "stage_id": stage.id}
        )

    def _create_non_matching(self):
        stage = self._won_stage()
        self.assertTrue(stage, "no won CRM stage exists")
        self.env["crm.lead"].create(
            {"name": "Won opportunity", "type": "opportunity", "stage_id": stage.id}
        )


@tagged("post_install", "-at_install")
class TestOverdueOpportunityCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_crm.area_crm"
    SIGNAL_KEY = "overdue_opportunities"
    MODEL = "crm.lead"
    DOMAIN = [
        ("type", "=", "opportunity"),
        ("date_deadline", "<", "$today"),
        ("stage_id.is_won", "=", False),
    ]

    def _create_matching(self):
        self.env["crm.lead"].create(
            {
                "name": "Past due opportunity",
                "type": "opportunity",
                "date_deadline": "2020-01-01",
            }
        )

    def _create_non_matching(self):
        # Same model, deadline in the future.
        self.env["crm.lead"].create(
            {
                "name": "Future opportunity",
                "type": "opportunity",
                "date_deadline": "2030-01-01",
            }
        )

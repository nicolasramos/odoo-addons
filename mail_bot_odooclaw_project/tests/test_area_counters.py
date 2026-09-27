# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestOpenProjectCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_project.area_proyectos"
    SIGNAL_KEY = "open_projects"
    MODEL = "project.project"
    DOMAIN = [("stage_id.fold", "=", False)]

    def _closed_stage(self):
        # Done / Cancelled are the stages with fold=True in a clean Odoo 18.
        return self.env["project.project.stage"].search(
            [("fold", "=", True)], limit=1
        )

    def _create_matching(self):
        # A project with no stage is still open: project.project has no `state`,
        # its lifecycle is stage_id, and only folded stages are closed.
        self.env["project.project"].create({"name": "Open project"})

    def _create_non_matching(self):
        stage = self._closed_stage()
        self.assertTrue(stage, "no folded project stage exists to close with")
        self.env["project.project"].create(
            {"name": "Closed project", "stage_id": stage.id}
        )


@tagged("post_install", "-at_install")
class TestOverdueProjectCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_project.area_proyectos_vencidos"
    SIGNAL_KEY = "overdue_projects"
    MODEL = "project.project"
    DOMAIN = [("date", "<", "$today"), ("stage_id.fold", "=", False)]

    def _create_matching(self):
        self.env["project.project"].create(
            {"name": "Past due project", "date": "2020-01-01"}
        )

    def _create_non_matching(self):
        # Same model, but the end date is in the future.
        self.env["project.project"].create(
            {"name": "Future project", "date": "2030-01-01"}
        )


@tagged("post_install", "-at_install")
class TestOverdueTaskCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_project.area_proyectos_tareas"
    SIGNAL_KEY = "overdue_tasks"
    MODEL = "project.task"
    DOMAIN = [
        ("date_deadline", "<", "$today"),
        ("state", "not in", ["1_done", "1_canceled"]),
    ]

    def _create_matching(self):
        self.env["project.task"].create(
            {
                "name": "Late task",
                "date_deadline": "2020-01-01",
                "state": "01_in_progress",
            }
        )

    def _create_non_matching(self):
        # Overdue, but already closed: it must NOT be counted.
        self.env["project.task"].create(
            {"name": "Late but done", "date_deadline": "2020-01-01", "state": "1_done"}
        )

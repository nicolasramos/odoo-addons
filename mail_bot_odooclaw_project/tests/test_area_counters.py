# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestOpenProjectCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_project.area_projects"
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
    AREA_XMLID = "mail_bot_odooclaw_project.area_projects_overdue"
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
    AREA_XMLID = "mail_bot_odooclaw_project.area_projects_tasks"
    SIGNAL_KEY = "overdue_tasks"
    MODEL = "project.task"
    # Odoo 16 project.task has no `state`: closure is the stage's fold flag.
    DOMAIN = [
        ("date_deadline", "<", "$today"),
        ("stage_id.fold", "=", False),
    ]

    def _stage(self, project, name, fold):
        # In Odoo 16 a task stage belongs to a project; a stage without one is
        # a personal stage and cannot be set on a project task.
        return self.env["project.task.type"].create(
            {"name": name, "fold": fold, "project_ids": [(4, project.id)]}
        )

    def _create_matching(self):
        project = self.env["project.project"].create({"name": "Late project"})
        self.env["project.task"].create(
            {
                "name": "Late task",
                "project_id": project.id,
                "stage_id": self._stage(project, "Open (counter test)", False).id,
                "date_deadline": "2020-01-01",
            }
        )

    def _create_non_matching(self):
        # Overdue, but already closed: it must NOT be counted.
        project = self.env["project.project"].create({"name": "Done project"})
        self.env["project.task"].create(
            {
                "name": "Late but done",
                "project_id": project.id,
                "stage_id": self._stage(project, "Done (counter test)", True).id,
                "date_deadline": "2020-01-01",
            }
        )

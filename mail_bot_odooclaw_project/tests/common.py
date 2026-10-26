# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class ProjectCounterCommon(TransactionCase):
    """Shared setup for project counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.Project = cls.env["project.project"].sudo()
        cls.Task = cls.env["project.task"].sudo()
        cls.Area.create(
            {
                "name": "Projects",
                "area": "projects",
                "sequence": 70,
                "enabled": True,
                "model_name": "project.project",
                "signal_definition": '{"still_open_projects": {"model": "project.project", "domain": [["stage_id.fold", "=", false]]}, "overdue_projects": {"model": "project.project", "domain": [["date_end", "<", "$today"], ["stage_id.fold", "=", false]]}, "overdue_tasks": {"model": "project.task", "domain": [["date_end", "<", "$today"], ["stage_id.fold", "=", false]]}, "open_tasks": {"model": "project.task", "domain": [["stage_id.fold", "=", false]]}, "waiting_tasks": {"model": "project.task", "domain": [["state", "=", "04_waiting_normal"]]}, "urgent_tasks": {"model": "project.task", "domain": [["priority", "=", "1"], ["stage_id.fold", "=", false]]}}',
            }
        )

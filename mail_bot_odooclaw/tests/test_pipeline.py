# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestPipeline(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.area = cls.env["mail.odooclaw.area"].create(
            {
                "name": "Test area",
                "area": "test",
                "model_name": "res.partner",
            }
        )
        cls.pipeline = cls.env["mail.odooclaw.pipeline"].create(
            {
                "area_id": cls.area.id,
                "mode": "draft",
            }
        )
        cls.stage_auto = cls.env["mail.odooclaw.pipeline.stage"].create(
            {
                "pipeline_id": cls.pipeline.id,
                "stage_id": 10,
                "stage_name": "Open",
                "mode": "auto",
            }
        )
        cls.stage_escalate = cls.env["mail.odooclaw.pipeline.stage"].create(
            {
                "pipeline_id": cls.pipeline.id,
                "stage_id": 20,
                "stage_name": "Closed",
                "escalate": True,
            }
        )

    def test_stage_rule_wins_over_the_default(self):
        self.assertEqual(self.pipeline.mode_for_stage(10), "auto")

    def test_stage_without_rule_uses_the_default(self):
        self.assertEqual(self.pipeline.mode_for_stage(99), "draft")
        self.assertEqual(self.pipeline.mode_for_stage(0), "draft")

    def test_rule_without_mode_inherits_and_still_escalates(self):
        self.assertEqual(self.pipeline.mode_for_stage(20), "draft")
        self.assertTrue(self.pipeline.escalate_for_stage(20))
        self.assertFalse(self.pipeline.escalate_for_stage(10))

    def test_inactive_rule_is_ignored(self):
        self.stage_auto.active = False
        self.assertEqual(self.pipeline.mode_for_stage(10), "draft")

    def test_one_rule_per_stage(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["mail.odooclaw.pipeline.stage"].create(
                {
                    "pipeline_id": self.pipeline.id,
                    "stage_id": 10,
                    "stage_name": "Duplicate",
                }
            )

    def test_run_keeps_its_snapshot(self):
        run = self.env["mail.odooclaw.pipeline.run"].create(
            {
                "pipeline_id": self.pipeline.id,
                "model_name": "res.partner",
                "res_id": 1,
                "res_name": "Azure Interior",
                "stage_id": 10,
                "stage_name": "Open",
                "mode": "auto",
                "state": "sent",
                "decision": "Customer asked about the delivery date; answered.",
            }
        )
        self.assertIn(run, self.pipeline.run_ids)
        self.assertEqual(self.pipeline.run_count, 1)


@tagged("post_install", "-at_install")
class TestSettings(TransactionCase):
    def test_settings_roundtrip(self):
        settings = self.env["res.config.settings"].create(
            {
                "odooclaw_pipeline_enabled": True,
                "odooclaw_pipeline_mode": "observe",
                "odooclaw_require_field_help": True,
            }
        )
        settings.execute()
        icp = self.env["ir.config_parameter"].sudo()
        self.assertEqual(icp.get_param("odooclaw.pipeline.enabled"), "True")
        self.assertEqual(icp.get_param("odooclaw.pipeline.mode"), "observe")
        self.assertEqual(icp.get_param("odooclaw.require_field_help"), "True")

    def test_repo_url_without_token_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["res.config.settings"].create(
                {
                    "odooclaw_repo_url": "git@example.com:bot.git",
                }
            )

    def test_pipeline_on_for_a_missing_module_is_refused(self):
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", "helpdesk_mgmt")], limit=1)
        )
        if module and module.state == "installed":
            self.skipTest("helpdesk_mgmt is installed in this database")
        area = self.env["mail.odooclaw.area"].create(
            {
                "name": "Helpdesk",
                "area": "helpdesk",
                "model_name": "helpdesk.ticket",
            }
        )
        self.env["mail.odooclaw.pipeline"].create({"area_id": area.id})
        with self.assertRaises(ValidationError):
            self.env["res.config.settings"].create(
                {
                    "odooclaw_pipeline_enabled": True,
                }
            )

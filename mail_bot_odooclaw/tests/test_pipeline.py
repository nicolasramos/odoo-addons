# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import os
import re

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
                "instructions": "Never quote prices or delivery dates.",
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
                "instructions": "Ask for the order number first.",
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


    def test_stage_instructions_are_only_the_stage_ones(self):
        self.assertEqual(
            self.pipeline.stage_instructions(20), "Ask for the order number first."
        )
        self.assertEqual(self.pipeline.stage_instructions(99), "")
        self.assertEqual(self.pipeline.stage_instructions(0), "")

    def test_area_instructions_survive_the_stage_rule(self):
        self.assertIn("Never quote prices", self.pipeline.instructions)
        self.assertEqual(self.pipeline.mode_for_stage(20), "draft")

    def test_use_knowledge_is_off_by_default(self):
        other = self.env["mail.odooclaw.area"].create(
            {"name": "Other", "area": "other", "model_name": "res.partner"}
        )
        pipeline = self.env["mail.odooclaw.pipeline"].create({"area_id": other.id})
        self.assertFalse(pipeline.use_knowledge)

    def test_use_knowledge_with_the_module_installed(self):
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", "mail_bot_odooclaw_knowledge")], limit=1)
        )
        if not module or module.state != "installed":
            self.skipTest("the knowledge module is not installed here")
        self.pipeline.use_knowledge = True
        self.assertTrue(self.pipeline.use_knowledge)


@tagged("post_install", "-at_install")
class TestSettings(TransactionCase):
    """The OdooClaw block offers only what the code actually reads.

    A control that writes a parameter nobody reads promises the administrator an
    effect that does not exist, and a token stored for a push nothing performs
    is a secret kept for nothing. The block is kept to the keys with a reader,
    and the test below fails if a new key ever arrives without one.
    """

    #: every key the block writes; each one must have a reader
    WIRED_KEYS = {
        "odooclaw.pipeline.enabled",
        "odooclaw.pipeline.escalate_user_id",
    }
    RETIRED_FIELDS = (
        "odooclaw_pipeline_mode",
        "odooclaw_require_field_help",
        "odooclaw_repo_url",
        "odooclaw_repo_branch",
        "odooclaw_repo_token",
        "odooclaw_repo_author",
    )

    def test_settings_roundtrip(self):
        settings = self.env["res.config.settings"].create(
            {
                "odooclaw_pipeline_enabled": True,
                "odooclaw_pipeline_escalate_user_id": self.env.user.id,
            }
        )
        settings.execute()
        icp = self.env["ir.config_parameter"].sudo()
        self.assertEqual(icp.get_param("odooclaw.pipeline.enabled"), "True")
        self.assertEqual(
            icp.get_param("odooclaw.pipeline.escalate_user_id"),
            str(self.env.user.id),
        )

    def test_the_retired_controls_are_gone(self):
        """The six controls are out of the model and out of the block."""
        for name in self.RETIRED_FIELDS:
            self.assertNotIn(
                name,
                self.env["res.config.settings"]._fields,
                "%s is still a setting" % name,
            )
        arch = self.env.ref(
            "mail_bot_odooclaw.res_config_settings_view_form"
        ).arch_db
        for name in self.RETIRED_FIELDS:
            self.assertNotIn(name, arch, "%s is still offered in the block" % name)
        self.assertIn("odooclaw_pipeline_enabled", arch)
        self.assertIn("odooclaw_pipeline_escalate_user_id", arch)

    def test_every_key_the_block_writes_has_a_reader(self):
        """No key leaves the settings block unread.

        This is the guard against the whole class of defect: the block may grow,
        but not with a control that does nothing.
        """
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(module_dir, "models", "res_config_settings.py"),
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        written = set(re.findall(r'config_parameter="([^"]+)"', source))
        self.assertEqual(written, self.WIRED_KEYS)

        readers = {}
        for folder in ("models", "controllers"):
            base = os.path.join(module_dir, folder)
            for name in sorted(os.listdir(base)):
                if not name.endswith(".py") or name == "res_config_settings.py":
                    continue
                with open(os.path.join(base, name), encoding="utf-8") as handle:
                    readers[name] = handle.read()
        for key in sorted(written):
            found = [name for name, src in readers.items() if key in src]
            self.assertTrue(
                found, "%s is written by the block and read by nothing" % key
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

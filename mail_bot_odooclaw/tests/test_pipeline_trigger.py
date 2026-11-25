# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import time
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPipelineTrigger(TransactionCase):
    """A comment on a pipelined record becomes a queued run and one job."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.area = cls.env["mail.odooclaw.area"].create(
            {
                "name": "Partners",
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
        cls.partner = cls.env["res.partner"].create({"name": "Pipeline Customer"})
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")

    def _post(self, body="Hello, when does my order ship?", subtype="mail.mt_comment"):
        return self.partner.message_post(
            body=body,
            message_type="comment",
            subtype_xmlid=subtype,
            author_id=self.env.user.partner_id.id,
        )

    def _wait_for(self, predicate, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def _install_knowledge_module(self):
        """Pretend the optional knowledge module is installed.

        The knowledge addon is a separate module a deployment may not ship, and
        the pipeline refuses the flag without it, so a test that turns the flag
        on has to say so instead of depending on what the base database happens
        to have.
        """
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", "mail_bot_odooclaw_knowledge")], limit=1)
        )
        if not module:
            module = (
                self.env["ir.module.module"]
                .sudo()
                .create({"name": "mail_bot_odooclaw_knowledge"})
            )
        module.write({"state": "installed"})
        return module

    def test_knowledge_toggle_is_refused_without_the_module(self):
        """The flag cannot be turned on where nothing would answer from it."""
        module = self.env["ir.module.module"].search(
            [("name", "=", "mail_bot_odooclaw_knowledge")], limit=1
        )
        # The test database may have the module installed; the gate is about the
        # module's state, so pin it for the length of the check and let the
        # transaction put it back.
        previous = module.state if module else False
        if module:
            module.write({"state": "uninstalled"})
        try:
            with self.assertRaises(ValidationError):
                self.pipeline.use_knowledge = True
        finally:
            if module:
                module.write({"state": previous})

    def test_comment_creates_a_queued_run_and_one_job(self):
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            message = self._post()
            run = self.env["mail.odooclaw.pipeline.run"].search(
                [("message_id", "=", message.id)]
            )
            self.assertEqual(len(run), 1)
            self.assertEqual(run.state, "queued")
            self.assertEqual(run.mode, "draft")
            self.assertEqual(run.model_name, "res.partner")
            self.assertEqual(run.res_id, self.partner.id)
            self.assertTrue(self._wait_for(lambda: post.called))
            payload = post.call_args.kwargs["json"]
            self.assertEqual(payload["run_id"], run.id)
            self.assertEqual(payload["message_id"], message.id)
            self.assertEqual(payload["model"], "res.partner")
            self.assertEqual(payload["mode"], "draft")
            self.assertIn("when does my order ship", payload["message_body"])

    def test_note_never_leaves_the_instance(self):
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            message = self._post(subtype="mail.mt_note")
            run = self.env["mail.odooclaw.pipeline.run"].search(
                [("message_id", "=", message.id)]
            )
            self.assertFalse(run)
            self.assertFalse(self._wait_for(lambda: post.called, timeout=0.3))

    def test_without_a_pipeline_nothing_is_queued(self):
        self.pipeline.active = False
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            message = self._post()
            run = self.env["mail.odooclaw.pipeline.run"].search(
                [("message_id", "=", message.id)]
            )
            self.assertFalse(run)
            self.assertFalse(self._wait_for(lambda: post.called, timeout=0.3))

    def test_the_bots_own_message_does_not_trigger(self):
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            message = self.partner.message_post(
                body="Here is your answer.",
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                author_id=self.bot.partner_id.id,
            )
            run = self.env["mail.odooclaw.pipeline.run"].search(
                [("message_id", "=", message.id)]
            )
            self.assertFalse(run)
            self.assertFalse(self._wait_for(lambda: post.called, timeout=0.3))

    def test_stage_rule_chooses_the_mode(self):
        stage = self.env["mail.odooclaw.pipeline.stage"].create(
            {
                "pipeline_id": self.pipeline.id,
                "stage_id": 7,
                "stage_name": "Waiting",
                "mode": "observe",
            }
        )
        self.assertEqual(self.pipeline.mode_for_stage(stage.stage_id), "observe")
        # The partner has no stage_id, so the area default applies.
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ):
            message = self._post()
            run = self.env["mail.odooclaw.pipeline.run"].search(
                [("message_id", "=", message.id)]
            )
            self.assertEqual(run.mode, "draft")

    def test_payload_carries_the_area_rules(self):
        self._install_knowledge_module()
        self.pipeline.instructions = "Never promise dates. Always ask for the order number."
        self.pipeline.use_knowledge = True
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            message = self._post()
            self.assertTrue(self._wait_for(lambda: post.called))
            payload = post.call_args.kwargs["json"]
            self.assertEqual(
                payload["instructions"],
                "Never promise dates. Always ask for the order number.",
            )
            self.assertEqual(payload["stage_instructions"], "")
            self.assertTrue(payload["use_knowledge"])
            self.assertEqual(payload["template_body"], "")

    def test_image_attachment_travels_with_the_job(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "factura.png",
                "raw": b"\x89PNG\r\n\x1a\nfake",
                "mimetype": "image/png",
                "res_model": "res.partner",
                "res_id": self.partner.id,
            }
        )
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            self.partner.message_post(
                body="Adjunto la factura.",
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                author_id=self.env.user.partner_id.id,
                attachment_ids=[attachment.id],
            )
            self.assertTrue(self._wait_for(lambda: post.called))
            payload = post.call_args.kwargs["json"]
            self.assertEqual(len(payload["attachments"]), 1)
            self.assertEqual(payload["attachments"][0]["mimetype"], "image/png")
            self.assertTrue(payload["attachments"][0]["data"])

    def test_a_pdf_is_not_sent_to_the_model(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "contrato.pdf",
                "raw": b"%PDF-1.4 fake",
                "mimetype": "application/pdf",
                "res_model": "res.partner",
                "res_id": self.partner.id,
            }
        )
        with patch(
            "odoo.addons.mail_bot_odooclaw.models.mail_thread.requests.post"
        ) as post:
            self.partner.message_post(
                body="Te paso el contrato.",
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                author_id=self.env.user.partner_id.id,
                attachment_ids=[attachment.id],
            )
            self.assertTrue(self._wait_for(lambda: post.called))
            payload = post.call_args.kwargs["json"]
            self.assertEqual(payload["attachments"], [])

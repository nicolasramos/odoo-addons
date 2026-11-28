# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPipelineFinish(TransactionCase):
    """The run applies the mode it was told to, on the real record."""

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
        cls.escalation_user = cls.env["res.users"].create(
            {
                "name": "Escalation Person",
                "login": "escalation.person@example.com",
                "email": "escalation.person@example.com",
            }
        )
        cls.pipeline = cls.env["mail.odooclaw.pipeline"].create(
            {
                "area_id": cls.area.id,
                "mode": "draft",
                "escalate_user_id": cls.escalation_user.id,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Finish Customer"})
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.pipeline_run = cls.env["mail.odooclaw.pipeline.run"].create(
            {
                "pipeline_id": cls.pipeline.id,
                "model_name": "res.partner",
                "res_id": cls.partner.id,
                "res_name": cls.partner.display_name,
                "mode": "draft",
            }
        )

    def _last_message(self):
        return self.partner.message_ids[:1]

    def test_drafted_leaves_an_internal_note(self):
        self.pipeline_run.apply_result(
            state="drafted",
            body="Your order ships on Tuesday.",
            decision="Asked about the delivery date.",
        )
        self.assertEqual(self.pipeline_run.state, "drafted")
        message = self._last_message()
        self.assertEqual(message.subtype_id, self.env.ref("mail.mt_note"))
        self.assertEqual(message.author_id, self.bot.partner_id)
        self.assertIn("ships on Tuesday", message.body)

    def test_sent_posts_a_comment_for_the_customer(self):
        self.pipeline_run.apply_result(
            state="sent",
            body="Your order ships on Tuesday.",
            decision="Answered the delivery date.",
        )
        message = self._last_message()
        self.assertEqual(message.subtype_id, self.env.ref("mail.mt_comment"))
        self.assertEqual(message.author_id, self.bot.partner_id)

    def test_observed_writes_nothing_on_the_record(self):
        before = len(self.partner.message_ids)
        self.pipeline_run.apply_result(state="observed", decision="Nothing worth saying.")
        self.assertEqual(self.pipeline_run.state, "observed")
        self.assertEqual(len(self.partner.message_ids), before)

    def test_failed_keeps_the_error(self):
        self.pipeline_run.apply_result(state="failed", error="model timed out")
        self.assertEqual(self.pipeline_run.error, "model timed out")

    def test_escalation_creates_an_activity_for_the_person(self):
        self.pipeline_run.apply_result(
            state="escalated",
            decision="The customer asks for a refund; needs a person.",
            escalate=True,
        )
        activity = self.env["mail.activity"].search(
            [("res_model", "=", "res.partner"), ("res_id", "=", self.partner.id)]
        )
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.escalation_user)

    def test_unknown_record_does_not_crash(self):
        self.pipeline_run.res_id = 999999
        self.pipeline_run.apply_result(state="sent", body="Anything")
        self.assertEqual(self.pipeline_run.state, "sent")

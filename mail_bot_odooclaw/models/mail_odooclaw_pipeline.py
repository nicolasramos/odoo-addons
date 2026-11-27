# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw operational pipeline.

Proactivity decides *when to speak*. This is the other half: what the bot does
when a customer writes, per area and per stage. One brain, two directions.

The pipeline is data, not code: an administrator picks the mode per area and,
when an area needs finer grain, per stage. Stage rules win over the area
default, which is what lets a helpdesk open the door with a draft and stay quiet
once the ticket is closed.

Modes:

* ``observe``: look and log, never write to the customer.
* ``draft``: write the reply as a draft for a human to review and send.
* ``auto``: answer directly.

Every field carries ``help``: a configuration field without an explanation is a
trap for whoever administers it six months later.
"""

from markupsafe import Markup

from datetime import timedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..utils.markdown_html import markdown_to_safe_html

MODE_SELECTION = [
    ("observe", "Observe only"),
    ("draft", "Draft for a human"),
    ("auto", "Answer directly"),
]

RUN_STATE_SELECTION = [
    ("queued", "Queued"),
    ("observed", "Observed"),
    ("drafted", "Drafted"),
    ("sent", "Sent"),
    ("escalated", "Escalated to a human"),
    ("skipped", "Skipped"),
    ("failed", "Failed"),
]


class MailOdooClawPipeline(models.Model):
    """Per-area behaviour when a message arrives on a record of that area."""

    _name = "mail.odooclaw.pipeline"
    _description = "OdooClaw Pipeline"
    _order = "area_id, id"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        help="Shown in lists. Comes from the area it belongs to.",
    )
    area_id = fields.Many2one(
        "mail.odooclaw.area",
        required=True,
        ondelete="cascade",
        help="Area this pipeline governs: helpdesk, crm, accounting...",
    )
    model_name = fields.Char(
        related="area_id.model_name",
        readonly=True,
        help="Technical model of the area, e.g. helpdesk.ticket.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to keep the configuration without applying it.",
    )
    enabled = fields.Boolean(
        default=True,
        help="When unchecked, incoming messages in this area are never processed "
        "even if the global switch is on.",
    )
    mode = fields.Selection(
        MODE_SELECTION,
        default="draft",
        required=True,
        help="What to do by default in this area. Stage rules can override it per "
        "stage.",
    )
    template_id = fields.Many2one(
        "mail.template",
        help="Optional template the agent starts from instead of composing from "
        "scratch.",
    )
    instructions = fields.Text(
        help="How the bot must act in this area: tone, what to ask, what never to "
        "promise, when to escalate. Written as rules a person would follow, short "
        "and concrete. Stage rules can add to it.",
    )
    use_knowledge = fields.Boolean(
        string="Use the knowledge base",
        default=False,
        help="When checked, the bot searches the knowledge document pages "
        "before answering and cites the page it used. Requires the "
        "mail_bot_odooclaw_knowledge module.",
    )
    escalate_user_id = fields.Many2one(
        "res.users",
        help="Who receives the work when the pipeline escalates: the bot cannot "
        "answer, or the customer asked for a person.",
    )
    escalate_after = fields.Integer(
        default=2,
        help="Consecutive turns without a useful answer before escalating. 0 "
        "disables automatic escalation.",
    )
    stage_rule_ids = fields.One2many(
        "mail.odooclaw.pipeline.stage",
        "pipeline_id",
        help="Per-stage overrides. A stage with no rule uses the area default.",
    )
    run_ids = fields.One2many(
        "mail.odooclaw.pipeline.run",
        "pipeline_id",
        readonly=True,
        help="History of what the pipeline did and why.",
    )
    run_count = fields.Integer(
        compute="_compute_run_count",
        help="How many runs this pipeline has recorded.",
    )

    _sql_constraints = [
        (
            "area_unique",
            "unique(area_id)",
            "One pipeline per area. Use the stage rules for finer behaviour.",
        ),
    ]

    @api.depends("area_id.name")
    def _compute_name(self):
        for pipeline in self:
            pipeline.name = pipeline.area_id.name or _("New pipeline")

    @api.depends("run_ids")
    def _compute_run_count(self):
        for pipeline in self:
            pipeline.run_count = len(pipeline.run_ids)

    def mode_for_stage(self, stage_id):
        """Effective mode for ``stage_id``; the stage rule wins over the default.

        ``stage_id`` is an integer because the stage models differ per area
        (helpdesk.ticket.stage, crm.stage) and a generic reference would force
        every area module to register its model here.
        """
        self.ensure_one()
        rule = self.stage_rule_ids.filtered(
            lambda r: r.active and r.stage_id == int(stage_id or 0)
        )[:1]
        return rule.mode or self.mode

    def escalate_for_stage(self, stage_id):
        """Whether this stage must go to a human, regardless of the mode."""
        self.ensure_one()
        rule = self.stage_rule_ids.filtered(
            lambda r: r.active and r.stage_id == int(stage_id or 0)
        )[:1]
        return bool(rule.escalate)

    def stage_instructions(self, stage_id):
        """Extra rules written for the stage, if any."""
        self.ensure_one()
        rule = self.stage_rule_ids.filtered(
            lambda r: r.active and r.stage_id == int(stage_id or 0)
        )[:1]
        return rule.instructions or ""

    @api.constrains("use_knowledge")
    def _check_knowledge_module(self):
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", "mail_bot_odooclaw_knowledge")], limit=1)
        )
        installed = bool(module and module.state == "installed")
        for pipeline in self:
            if pipeline.use_knowledge and not installed:
                raise ValidationError(
                    _(
                        "The knowledge base is on for %(area)s but the module "
                        "mail_bot_odooclaw_knowledge is not installed. Install it "
                        "or uncheck 'Use the knowledge base'.",
                        area=pipeline.area_id.name or pipeline.name,
                    )
                )


class MailOdooClawPipelineStage(models.Model):
    """Behaviour override for one stage of the pipeline's area."""

    _name = "mail.odooclaw.pipeline.stage"
    _description = "OdooClaw Pipeline Stage Rule"
    _order = "pipeline_id, sequence, id"

    pipeline_id = fields.Many2one(
        "mail.odooclaw.pipeline",
        required=True,
        ondelete="cascade",
        help="Pipeline this rule belongs to.",
    )
    model_name = fields.Char(
        related="pipeline_id.model_name",
        readonly=True,
        help="Technical model of the stage, inherited from the pipeline.",
    )
    sequence = fields.Integer(
        default=10,
        help="Order of the rules in the form. Does not affect matching.",
    )
    stage_id = fields.Integer(
        required=True,
        string="Stage ID",
        help="Database id of the stage record. The stage model depends on the "
        "area: helpdesk.ticket.stage for helpdesk, crm.stage for crm.",
    )
    stage_name = fields.Char(
        required=True,
        help="Stage name as the administrator sees it. Informative: matching uses "
        "the id, never the name, because names repeat across teams.",
    )
    mode = fields.Selection(
        MODE_SELECTION,
        help="Leave empty to inherit the pipeline's mode.",
    )
    template_id = fields.Many2one(
        "mail.template",
        help="Template for this stage. Overrides the pipeline's template.",
    )
    instructions = fields.Text(
        help="Extra rules for this stage only. They are added after the area's "
        "instructions, so a stage can refine them without repeating them.",
    )
    escalate = fields.Boolean(
        help="Send the work to the pipeline's escalation user when the record is "
        "in this stage, whatever the mode says.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to disable this rule without deleting it.",
    )

    _sql_constraints = [
        (
            "pipeline_stage_unique",
            "unique(pipeline_id, stage_id)",
            "This stage already has a rule in this pipeline.",
        ),
    ]

    @api.constrains("stage_id")
    def _check_stage_id(self):
        for rule in self:
            if rule.stage_id <= 0:
                raise ValidationError(
                    _("The stage ID must be a positive database id, got %(value)s.")
                    % {"value": rule.stage_id}
                )


class MailOdooClawPipelineRun(models.Model):
    """One decision the pipeline took on one record, with its reason."""

    _name = "mail.odooclaw.pipeline.run"
    _description = "OdooClaw Pipeline Run"
    _order = "create_date desc, id desc"

    pipeline_id = fields.Many2one(
        "mail.odooclaw.pipeline",
        required=True,
        ondelete="cascade",
        help="Pipeline that produced this run.",
    )
    model_name = fields.Char(
        required=True,
        help="Model of the record the pipeline looked at.",
    )
    res_id = fields.Integer(
        required=True,
        help="Id of the record the pipeline looked at.",
    )
    res_name = fields.Char(
        help="Display name of the record at the time of the run, kept as a "
        "snapshot so the history survives a rename or a delete.",
    )
    message_id = fields.Many2one(
        "mail.message",
        ondelete="set null",
        help="Message that triggered the run, when a customer reply did.",
    )
    stage_id = fields.Integer(
        help="Stage id at the time of the run.",
    )
    stage_name = fields.Char(
        help="Stage name at the time of the run.",
    )
    mode = fields.Selection(
        MODE_SELECTION,
        help="Effective mode applied: the stage rule if there was one, otherwise "
        "the pipeline default.",
    )
    state = fields.Selection(
        RUN_STATE_SELECTION,
        default="queued",
        required=True,
        help="What the run ended up doing.",
    )
    decision = fields.Text(
        help="Why the pipeline took this decision, in plain words.",
    )
    attachment_text = fields.Text(
        string="Attachment Text",
        readonly=True,
        help="What the multimodal model read from the images and voice notes of the message: text for a person to check, not a customer field.",
    )
    error = fields.Text(
        help="Failure detail when the run ended in error.",
    )

    @api.model
    def _cron_requeue_stale(self):
        """Re-send the runs the engine lost, for example when it restarted.

        The queue lives in the engine's memory, so a restart drops whatever was
        waiting. A run stuck in queued is invisible work: here it is sent again
        with the same message and the old row keeps the reason.
        """
        icp = self.env["ir.config_parameter"].sudo()
        if icp.get_param("odooclaw.pipeline.enabled", "True").strip().lower() in (
            "false",
            "0",
            "no",
        ):
            return
        # An engine that is down must not turn this into a loop: the run stays
        # queued and waits. Only a healthy engine that lost the job is retried.
        job_url = icp.get_param(
            "odooclaw.pipeline_url", "http://odooclaw:18790/odooclaw/job"
        )
        health_url = job_url.replace("/odooclaw/job", "/health")
        try:
            import requests

            if requests.get(health_url, timeout=3).status_code != 200:
                return
        except Exception:  # noqa: BLE001 - no health, no requeue
            return
        minutes = int(icp.get_param("odooclaw.pipeline.requeue_after_minutes", "30"))
        cutoff = fields.Datetime.now() - timedelta(minutes=minutes)
        stale = self.search([("state", "=", "queued"), ("create_date", "<", cutoff)])
        bot_user = (
            self.env["res.users"]
            .sudo()
            .search([("login", "=", "odooclaw_bot")], limit=1)
        )
        for run in stale:
            message = run.message_id
            if not message or not bot_user:
                run.write(
                    {
                        "state": "failed",
                        "error": "job lost; the original message cannot be replayed",
                    }
                )
                continue
            try:
                self.env["mail.thread"]._odooclaw_trigger_pipeline(
                    message, bot_user
                )
            except Exception as error:  # noqa: BLE001 - the run keeps the detail
                run.write(
                    {
                        "state": "failed",
                        "error": "job lost; requeue failed: %s" % error,
                    }
                )
                continue
            run.write(
                {
                    "state": "failed",
                    "error": "job lost on engine restart; resent as a new run",
                }
            )

    @api.constrains("res_id")
    def _check_res_id(self):
        for run in self:
            if run.res_id <= 0:
                raise ValidationError(
                    _("The record id must be positive, got %(value)s.")
                    % {"value": run.res_id}
                )

    def apply_result(
        self, state, body="", decision="", error="", escalate=False,
        attachment_text="",
    ):
        """Write the outcome of a run and apply its effect on the record.

        ``drafted`` becomes an internal note with the proposed reply, so a
        person reads it in the chatter before anyone outside sees it. ``sent``
        becomes a comment visible to the customer, written as the bot.
        ``observed``, ``failed`` and ``skipped`` only land in the log. An
        escalation adds a mail activity for the pipeline's escalation user.
        """
        self.ensure_one()
        values = {
            "state": state,
            "decision": decision or self.decision,
            "error": error or "",
        }
        if attachment_text:
            values["attachment_text"] = attachment_text
        self.write(values)
        record = self.env[self.model_name].sudo().browse(self.res_id)
        if not record.exists():
            return self
        bot = self.env.ref(
            "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
        )
        if body and state in ("drafted", "sent") and bot:
            subtype = "mail.mt_note" if state == "drafted" else "mail.mt_comment"
            record.with_user(bot).sudo().message_post(
                body=Markup(markdown_to_safe_html(body)),
                author_id=bot.partner_id.id,
                message_type="comment",
                subtype_xmlid=subtype,
            )
        if escalate and self.pipeline_id.escalate_user_id:
            activity_type = (
                self.env["mail.activity.type"].sudo().search([], limit=1)
            )
            model = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", self.model_name)], limit=1)
            )
            self.env["mail.activity"].sudo().create(
                {
                    "res_model": self.model_name,
                    "res_model_id": model.id,
                    "res_id": self.res_id,
                    "user_id": self.pipeline_id.escalate_user_id.id,
                    "activity_type_id": activity_type.id,
                    "summary": _("OdooClaw: needs a person"),
                    "note": decision or "",
                }
            )
        return self

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

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

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
    error = fields.Text(
        help="Failure detail when the run ended in error.",
    )

    @api.constrains("res_id")
    def _check_res_id(self):
        for run in self:
            if run.res_id <= 0:
                raise ValidationError(
                    _("The record id must be positive, got %(value)s.")
                    % {"value": run.res_id}
                )

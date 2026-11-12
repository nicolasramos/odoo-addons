# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class AgentStageMap(models.Model):
    _name = 'odoo.agent.stage.map'
    _description = 'Agent Status to Project Stage Mapping'
    _order = 'agent_status, id'
    _rec_name = 'display_name'
    _check_company_auto = True

    agent_status = fields.Selection(
        [
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('waiting_input', 'Waiting for Input'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancel_requested', 'Cancel Requested'),
            ('cancelled', 'Cancelled'),
            ('pending', 'Legacy Pending'),
            ('in_progress', 'Legacy In Progress'),
        ],
        string='Agent Status',
        required=True,
        index=True,
    )
    stage_id = fields.Many2one(
        'project.task.type',
        string='Project Stage',
        required=True,
        ondelete='cascade',
        domain="[('fold', '=', False)]",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)

    _agent_status_company_unique = models.Constraint(
        'unique(agent_status, company_id)',
        "Each agent status can only have one mapping per company.",
    )

    @api.depends('agent_status', 'stage_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.get_agent_status_display()} -> {rec.stage_id.name}'

    def get_agent_status_display(self):
        self.ensure_one()
        return dict(self._fields['agent_status'].selection).get(self.agent_status, self.agent_status)

    @api.model
    def get_stage_for_status(self, agent_status, company_id=None, project=None):
        if not company_id:
            company_id = self.env.company.id
        mapping = self.search([
            ('agent_status', '=', agent_status),
            ('company_id', '=', company_id),
        ], limit=1)
        if mapping and self._stage_matches_project(mapping.stage_id, project):
            return mapping.stage_id
        return self.env['project.task.type']

    @api.model
    def _stage_matches_project(self, stage, project):
        if not stage or not project:
            return bool(stage)
        return not stage.project_ids or project in stage.project_ids

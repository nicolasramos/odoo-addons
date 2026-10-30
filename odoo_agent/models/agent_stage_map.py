# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class AgentStageMap(models.Model):
    _name = 'odoo.agent.stage.map'
    _description = 'Agent Status to Project Stage Mapping'
    _order = 'project_id, agent_status, id'
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
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        ondelete='cascade',
        index=True,
        help='Leave empty to apply this mapping to every project of the company. '
             'A project specific mapping always wins over the company wide one.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)

    _sql_constraints = [
        (
            'agent_status_project_company_unique',
            'unique(agent_status, company_id, project_id)',
            'Each agent status can only have one mapping per project and company.',
        ),
    ]

    def init(self):
        # ``project_id`` is nullable and PostgreSQL treats NULLs as distinct in a
        # unique constraint, so the SQL constraint above does not prevent two
        # company wide fallbacks. A partial unique index does.
        self.env.cr.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS odoo_agent_stage_map_company_default_uniq
            ON odoo_agent_stage_map (agent_status, company_id)
            WHERE project_id IS NULL
        ''')

    @api.depends('agent_status', 'stage_id', 'project_id')
    def _compute_display_name(self):
        for rec in self:
            scope = rec.project_id.display_name or 'All projects'
            rec.display_name = f'{rec.get_agent_status_display()} -> {rec.stage_id.name} ({scope})'

    def get_agent_status_display(self):
        self.ensure_one()
        return dict(self._fields['agent_status'].selection).get(self.agent_status, self.agent_status)

    @api.model
    def get_stage_for_status(self, agent_status, company_id=None, project=None):
        """Return the stage configured for ``agent_status``.

        Resolution order is the project specific mapping first and the company
        wide mapping second. An empty recordset means no mapping is configured,
        and callers must leave the task stage untouched.
        """
        if not company_id:
            company_id = self.env.company.id
        base_domain = [
            ('agent_status', '=', agent_status),
            ('company_id', '=', company_id),
        ]
        if project:
            mapping = self.search(base_domain + [('project_id', '=', project.id)], limit=1)
            if mapping:
                return mapping.stage_id
        mapping = self.search(base_domain + [('project_id', '=', False)], limit=1)
        if mapping:
            return mapping.stage_id
        return self.env['project.task.type']

    @api.model
    def _stage_matches_project(self, stage, project):
        """Backward compatible helper kept for external callers."""
        if not stage or not project:
            return bool(stage)
        return not stage.project_ids or project in stage.project_ids

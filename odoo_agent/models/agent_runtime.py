# Part of Odoo. See LICENSE file for full copyright and licensing details.

import secrets

from odoo import api, fields, models


class AgentRuntime(models.Model):
    _name = 'odoo.agent.runtime'
    _description = 'AI Agent Runtime'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, index=True)
    machine_id = fields.Char(
        string='Machine ID',
        required=True,
        index=True,
        help='Unique machine identifier (hostname or UUID)',
    )
    ip_address = fields.Char(string='IP Address')
    status = fields.Selection(
        [
            ('offline', 'Offline'),
            ('online', 'Online'),
            ('busy', 'Busy'),
        ],
        string='Status',
        default='offline',
        required=True,
        index=True,
    )
    last_seen = fields.Datetime(string='Last Seen')
    api_key = fields.Char(
        string='API Key',
        help='API key for runtime authentication',
        index=True,
        groups='odoo_agent.group_agent_admin',
    )
    version = fields.Char(string='Version', help='Daemon/CLI version')
    device_info = fields.Char(string='Device Info', help='OS, hardware info')
    capabilities = fields.Text(string='Capabilities')
    agent_ids = fields.One2many(
        'odoo.agent', 'runtime_id', string='Agents',
    )
    execution_ids = fields.One2many(
        'odoo.agent.execution', 'runtime_id', string='Executions',
    )
    active_agent_count = fields.Integer(
        string='Active Agents',
        compute='_compute_active_agent_count',
    )
    queued_execution_count = fields.Integer(
        string='Queued Executions',
        compute='_compute_execution_counts',
    )
    running_execution_count = fields.Integer(
        string='Running Executions',
        compute='_compute_execution_counts',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    _machine_id_unique = models.Constraint(
        'unique(machine_id, company_id)',
        "Machine ID must be unique per company.",
    )

    @api.depends('agent_ids', 'agent_ids.status')
    def _compute_active_agent_count(self):
        for runtime in self:
            runtime.active_agent_count = len(runtime.agent_ids.filtered(lambda a: a.status == 'working'))

    @api.depends('execution_ids', 'execution_ids.status')
    def _compute_execution_counts(self):
        for runtime in self:
            runtime.queued_execution_count = len(runtime.execution_ids.filtered(lambda e: e.status == 'queued'))
            runtime.running_execution_count = len(runtime.execution_ids.filtered(lambda e: e.status in ('running', 'waiting_input')))

    def action_generate_api_key(self):
        self.ensure_one()
        self.api_key = secrets.token_urlsafe(32)

    def action_mark_online(self):
        self.write({'status': 'online', 'last_seen': fields.Datetime.now()})

    def action_mark_offline(self):
        self.write({'status': 'offline'})
        for runtime in self:
            runtime.agent_ids.filtered(lambda agent: agent.status == 'working').write({'status': 'error'})

    def action_view_executions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Runtime Executions',
            'res_model': 'odoo.agent.execution',
            'view_mode': 'list,form',
            'domain': [('runtime_id', '=', self.id)],
            'context': {'default_runtime_id': self.id},
        }

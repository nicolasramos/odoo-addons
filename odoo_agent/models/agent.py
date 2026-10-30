# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from odoo import api, fields, models


class Agent(models.Model):
    _name = 'odoo.agent'
    _description = 'AI Agent'
    _order = 'name, id'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, index=True, tracking=True)
    mention_key = fields.Char(
        string='Mention Handle',
        index=True,
        tracking=True,
        help='Short handle used to mention this agent from prompts, for example @qa or @hermes.',
    )
    description = fields.Text(string='Description')
    instructions = fields.Text(
        string='Instructions',
        help='System prompt / instructions for the agent',
    )
    runtime_id = fields.Many2one(
        'odoo.agent.runtime',
        string='Runtime',
        ondelete='set null',
        tracking=True,
        check_company=True,
    )
    engine = fields.Selection(
        [
            ('codex', 'Codex'),
            ('hermes', 'Hermes'),
            ('opencode', 'OpenCode'),
            ('openclaw', 'OpenClaw'),
            ('claude', 'Claude Code'),
            ('custom', 'Custom CLI'),
        ],
        string='Engine',
        default='codex',
        required=True,
        tracking=True,
    )
    cli_command = fields.Char(
        string='CLI Command',
        default='codex',
        help='Command executed by the runtime for this agent.',
    )
    model = fields.Char(string='Model', help='LLM model to use')
    status = fields.Selection(
        [
            ('idle', 'Idle'),
            ('working', 'Working'),
            ('error', 'Error'),
        ],
        string='Status',
        default='idle',
        required=True,
        index=True,
        tracking=True,
    )
    avatar = fields.Binary(string='Avatar')
    skill_ids = fields.Many2many(
        'odoo.agent.skill',
        'agent_skill_rel',
        'agent_id',
        'skill_id',
        string='Skills',
    )
    mcp_server_ids = fields.Many2many(
        'odoo.agent.mcp.server',
        'agent_mcp_server_rel',
        'agent_id',
        'mcp_server_id',
        string='MCP Servers',
    )
    max_concurrent_executions = fields.Integer(
        string='Max Concurrent Executions',
        default=1,
        required=True,
    )
    max_concurrent_tasks = fields.Integer(
        string='Legacy Max Concurrent Tasks',
        default=1,
        help='Compatibility field. Use Max Concurrent Executions for new runtime dispatch.',
    )
    timeout_seconds = fields.Integer(string='Timeout (seconds)', default=3600, required=True)
    retry_limit = fields.Integer(string='Retry Limit', default=0, required=True)
    dispatch_on_assign = fields.Boolean(
        string='Dispatch On Assignment',
        default=True,
        help='Queue an execution automatically when a record is assigned to this agent. '
             'Disable it for agents that must only run on demand.',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Linked User',
        help='Optional: link to an Odoo user for permissions',
    )
    execution_ids = fields.One2many(
        'odoo.agent.execution',
        'agent_id',
        string='Executions',
    )
    active_execution_count = fields.Integer(
        string='Active Executions',
        compute='_compute_active_execution_count',
    )
    task_ids = fields.One2many(
        'odoo.agent.task', 'agent_id', string='Legacy Tasks',
    )
    active_task_count = fields.Integer(
        string='Legacy Active Tasks',
        compute='_compute_active_task_count',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        (
            'mention_key_company_unique',
            'unique(mention_key, company_id)',
            'The mention handle must be unique per company.',
        ),
    ]

    @api.onchange('engine')
    def _onchange_engine(self):
        """Auto-populate cli_command when the engine selection changes."""
        engine_defaults = {
            'codex': 'codex exec --model {model}',
            'hermes': 'hermes run --context {instruction}',
            'opencode': 'opencode run --model {model}',
            'openclaw': 'openclaw agent --task {task_name} --context {instruction}',
            'claude': 'claude --print {instruction}',
            'custom': '',
        }
        if self.engine in engine_defaults:
            self.cli_command = engine_defaults[self.engine]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name') and not vals.get('mention_key'):
                vals['mention_key'] = self._normalize_mention_key(vals['name'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('mention_key'):
            vals['mention_key'] = self._normalize_mention_key(vals['mention_key'])
        return super().write(vals)

    @api.model
    def _normalize_mention_key(self, value):
        value = (value or '').strip().lower()
        value = re.sub(r'[^a-z0-9_.-]+', '-', value)
        return value.strip('-') or False

    @api.model
    def resolve_mention_tokens(self, tokens, company=None):
        normalized_tokens = {
            self._normalize_mention_key(token)
            for token in tokens
            if self._normalize_mention_key(token)
        }
        if not normalized_tokens:
            return self.browse()
        domain = [('active', '=', True)]
        if company:
            domain.append(('company_id', '=', company.id))
        candidates = self.search(domain)
        return candidates.filtered(
            lambda agent: (
                agent.mention_key in normalized_tokens
                or self._normalize_mention_key(agent.name) in normalized_tokens
            )
        )

    @api.depends('execution_ids', 'execution_ids.status')
    def _compute_active_execution_count(self):
        for agent in self:
            agent.active_execution_count = len(
                agent.execution_ids.filtered(lambda e: e.status in ('queued', 'running', 'waiting_input', 'cancel_requested'))
            )

    @api.depends('task_ids', 'task_ids.status')
    def _compute_active_task_count(self):
        for agent in self:
            agent.active_task_count = len(
                agent.task_ids.filtered(lambda t: t.status in ('pending', 'in_progress'))
            )

    def action_assign_runtime(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assign Runtime',
            'res_model': 'odoo.agent.runtime',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_executions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Executions',
            'res_model': 'odoo.agent.execution',
            'view_mode': 'list,form',
            'domain': [('agent_id', '=', self.id)],
            'context': {'default_agent_id': self.id, 'default_runtime_id': self.runtime_id.id},
        }

    def _refresh_status_from_executions(self):
        for agent in self:
            running = agent.execution_ids.filtered(lambda e: e.status in ('running', 'waiting_input'))
            queued = agent.execution_ids.filtered(lambda e: e.status in ('queued', 'cancel_requested'))
            failed = agent.execution_ids[:1].filtered(lambda e: e.status == 'failed')
            if running or queued:
                agent.status = 'working'
            elif failed:
                agent.status = 'error'
            else:
                agent.status = 'idle'

    def _get_final_prompt(self, execution=None):
        self.ensure_one()
        parts = []
        if self.instructions:
            parts.append(self.instructions)
        for skill in self.skill_ids:
            parts.append('## Skill: %s\n%s' % (skill.name, skill.instructions or ''))
        if execution and execution.prompt:
            parts.append('## Task\n%s' % execution.prompt)
        return '\n\n'.join(parts)

    def to_runtime_config(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'mention_key': self.mention_key,
            'engine': self.engine,
            'cli_command': self.cli_command,
            'model': self.model,
            'timeout_seconds': self.timeout_seconds,
            'retry_limit': self.retry_limit,
            'max_concurrent_executions': self.max_concurrent_executions,
            'linked_user_id': self.user_id.id if self.user_id else None,
            'instructions': self.instructions or '',
            'skills': [
                {
                    'id': skill.id,
                    'name': skill.name,
                    'category': skill.category,
                    'instructions': skill.instructions,
                }
                for skill in self.skill_ids
            ],
            'mcp_servers': [server.to_runtime_config() for server in self.mcp_server_ids],
        }

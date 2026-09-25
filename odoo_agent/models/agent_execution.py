# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AgentExecution(models.Model):
    _name = 'odoo.agent.execution'
    _description = 'Agent Execution'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id'
    _check_company_auto = True

    name = fields.Char(string='Title', required=True, tracking=True)
    prompt = fields.Text(string='Prompt')
    agent_id = fields.Many2one(
        'odoo.agent',
        string='Agent',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        check_company=True,
    )
    runtime_id = fields.Many2one(
        'odoo.agent.runtime',
        string='Runtime',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        check_company=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    task_id = fields.Many2one(
        'project.task',
        string='Project Task',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    requested_by_id = fields.Many2one(
        'res.users',
        string='Requested By',
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )
    parent_id = fields.Many2one(
        'odoo.agent.execution',
        string='Parent Execution',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    child_ids = fields.One2many(
        'odoo.agent.execution',
        'parent_id',
        string='Child Executions',
    )
    child_execution_count = fields.Integer(
        string='Delegated Executions',
        compute='_compute_child_execution_count',
    )
    mentioned_agent_ids = fields.Many2many(
        'odoo.agent',
        'agent_execution_mentioned_agent_rel',
        'execution_id',
        'agent_id',
        string='Mentioned Agents',
        copy=False,
        help='Agents mentioned in the prompt with @handle.',
    )
    legacy_agent_task_id = fields.Many2one(
        'odoo.agent.task',
        string='Legacy Agent Task',
        ondelete='set null',
        index=True,
        copy=False,
    )
    source = fields.Selection(
        [
            ('task', 'Project Task'),
            ('chat', 'Chat'),
            ('manual', 'Manual'),
        ],
        string='Source',
        default='task',
        required=True,
        index=True,
        copy=False,
    )
    chat_message_id = fields.Many2one(
        'odoo.agent.chat.message',
        string='Source Chat Message',
        ondelete='set null',
        index=True,
        copy=False,
        check_company=True,
    )
    chat_message_ids = fields.One2many(
        'odoo.agent.chat.message',
        'execution_id',
        string='Chat Messages',
    )
    status = fields.Selection(
        [
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('waiting_input', 'Waiting for Input'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancel_requested', 'Cancel Requested'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='queued',
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    result = fields.Text(string='Result', copy=False)
    error_message = fields.Text(string='Error Message', copy=False)
    cancellation_reason = fields.Text(string='Cancellation Reason', copy=False)
    started_at = fields.Datetime(string='Started At', copy=False)
    completed_at = fields.Datetime(string='Completed At', copy=False)
    last_heartbeat_at = fields.Datetime(string='Last Heartbeat', copy=False)
    attempt = fields.Integer(string='Attempt', default=1, required=True, copy=False)
    timeout_seconds = fields.Integer(string='Timeout (seconds)', default=3600)
    retry_limit = fields.Integer(string='Retry Limit', default=0)
    engine = fields.Selection(
        related='agent_id.engine',
        string='Engine',
        readonly=True,
        store=True,
    )
    log_ids = fields.One2many(
        'odoo.agent.log',
        'execution_id',
        string='Logs',
    )
    log_count = fields.Integer(string='Log Count', compute='_compute_log_count')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    def _auto_init(self):
        return super()._auto_init()

    def init(self):
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS idx_agent_execution_runtime_status_create
            ON odoo_agent_execution (runtime_id, status, create_date)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS idx_agent_execution_create_date
            ON odoo_agent_execution (create_date)
        ''')

    @api.depends('log_ids')
    def _compute_log_count(self):
        for execution in self:
            execution.log_count = len(execution.log_ids)

    @api.depends('child_ids')
    def _compute_child_execution_count(self):
        for execution in self:
            execution.child_execution_count = len(execution.child_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            agent = self.env['odoo.agent'].browse(vals.get('agent_id')) if vals.get('agent_id') else False
            task = self.env['project.task'].browse(vals.get('task_id')) if vals.get('task_id') else False
            if agent:
                vals.setdefault('runtime_id', agent.runtime_id.id)
                vals.setdefault('timeout_seconds', agent.timeout_seconds)
                vals.setdefault('retry_limit', agent.retry_limit)
                vals.setdefault('company_id', agent.company_id.id or self.env.company.id)
            if task:
                vals.setdefault('project_id', task.project_id.id)
                vals.setdefault('company_id', task.company_id.id or self.env.company.id)
            if not vals.get('runtime_id'):
                raise UserError(_('The selected agent must have a runtime before creating an execution.'))
        executions = super().create(vals_list)
        for execution in executions:
            mentioned_agents = execution._get_prompt_mentioned_agents()
            if mentioned_agents:
                execution.mentioned_agent_ids = [(6, 0, mentioned_agents.ids)]
            if execution.task_id:
                execution.task_id.latest_execution_id = execution.id
                execution.task_id.message_post(
                    body=Markup(_('Agent execution queued for <b>%s</b>.')) % escape(execution.agent_id.display_name),
                    subject=_('Agent execution queued'),
                )
            if not self.env.context.get('skip_agent_mentions'):
                execution._create_mentioned_agent_executions(mentioned_agents)
            execution._sync_project_task_stage()
            execution._notify_execution_event('execution_updated')
        return executions

    def write(self, vals):
        result = super().write(vals)
        if {'status', 'result', 'error_message', 'cancellation_reason', 'last_heartbeat_at'} & set(vals):
            for execution in self:
                execution._notify_execution_event('execution_updated')
        return result

    @api.model
    def get_queued_for_runtime(self, runtime, limit=10):
        return self.search([
            ('status', '=', 'queued'),
            ('runtime_id', '=', runtime.id),
        ], order='create_date asc, id asc', limit=limit)

    def action_start(self):
        for execution in self:
            if execution.status not in ('queued', 'cancel_requested'):
                continue
            execution.write({
                'status': 'running',
                'started_at': fields.Datetime.now(),
                'last_heartbeat_at': fields.Datetime.now(),
            })
            execution.agent_id.status = 'working'
            execution._sync_project_task_stage()

    def action_complete(self, result=None):
        for execution in self:
            vals = {
                'status': 'completed',
                'completed_at': fields.Datetime.now(),
                'error_message': False,
            }
            if result is not None:
                vals['result'] = result
            execution.write(vals)
            execution._create_chat_reply(result)
            execution._after_finished(Markup(_('<p>Agent <b>%s</b> completed execution <b>%s</b>.</p>')) % (
                escape(execution.agent_id.display_name),
                escape(execution.display_name),
            ))

    def action_fail(self, error_message=None):
        for execution in self:
            vals = {
                'status': 'failed',
                'completed_at': fields.Datetime.now(),
            }
            if error_message:
                vals['error_message'] = error_message
            execution.write(vals)
            execution._mark_chat_failed()
            execution._after_finished(Markup(_('<p>Agent <b>%s</b> failed execution <b>%s</b>.</p><p>%s</p>')) % (
                escape(execution.agent_id.display_name),
                escape(execution.display_name),
                escape(error_message or ''),
            ))

    def action_request_cancel(self):
        for execution in self:
            if execution.status in ('completed', 'failed', 'cancelled'):
                continue
            execution.write({
                'status': 'cancel_requested',
                'cancellation_reason': execution.cancellation_reason or _('Cancellation requested from Odoo.'),
            })
            execution._sync_project_task_stage()

    def action_ack_cancelled(self, reason=None):
        for execution in self:
            vals = {
                'status': 'cancelled',
                'completed_at': fields.Datetime.now(),
            }
            if reason:
                vals['cancellation_reason'] = reason
            execution.write(vals)
            execution._mark_chat_failed()
            execution._after_finished(
                Markup(_('<p>Agent execution <b>%s</b> was cancelled.</p>')) % escape(execution.display_name)
            )

    def action_retry(self):
        self.ensure_one()
        return self.env['odoo.agent.execution'].create({
            'name': self.name,
            'prompt': self.prompt,
            'agent_id': self.agent_id.id,
            'runtime_id': self.agent_id.runtime_id.id,
            'project_id': self.project_id.id,
            'task_id': self.task_id.id,
            'parent_id': self.id,
            'attempt': self.attempt + 1,
            'requested_by_id': self.env.user.id,
            'company_id': self.company_id.id,
            'source': self.source,
            'chat_message_id': self.chat_message_id.id,
        })

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Execution Logs'),
            'res_model': 'odoo.agent.log',
            'view_mode': 'list,form',
            'domain': [('execution_id', '=', self.id)],
            'context': {'default_execution_id': self.id},
        }

    def action_view_child_executions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delegated Executions'),
            'res_model': 'odoo.agent.execution',
            'view_mode': 'list,form',
            'domain': [('parent_id', '=', self.id)],
            'context': {
                'default_parent_id': self.id,
                'default_project_id': self.project_id.id,
                'default_task_id': self.task_id.id,
            },
        }

    def _extract_mention_tokens(self):
        self.ensure_one()
        return re.findall(r'@([A-Za-z0-9_.-]+)', self.prompt or '')

    def _get_prompt_mentioned_agents(self):
        self.ensure_one()
        return self.env['odoo.agent'].resolve_mention_tokens(
            self._extract_mention_tokens(),
            company=self.company_id,
        )

    def _create_mentioned_agent_executions(self, mentioned_agents):
        self.ensure_one()
        if self.parent_id or not mentioned_agents:
            return self.env['odoo.agent.execution']

        child_vals = []
        skipped_agents = self.env['odoo.agent']
        for agent in mentioned_agents:
            if agent == self.agent_id:
                continue
            if not agent.runtime_id:
                skipped_agents |= agent
                continue
            child_vals.append({
                'name': _('%(parent)s → %(agent)s') % {
                    'parent': self.name,
                    'agent': agent.display_name,
                },
                'prompt': self._build_delegated_prompt(agent),
                'agent_id': agent.id,
                'runtime_id': agent.runtime_id.id,
                'project_id': self.project_id.id,
                'task_id': self.task_id.id,
                'parent_id': self.id,
                'requested_by_id': self.requested_by_id.id,
                'company_id': self.company_id.id,
            })

        children = self.env['odoo.agent.execution'].with_context(skip_agent_mentions=True).create(child_vals)
        if self.task_id and children:
            body = Markup(_('<p><b>%s</b> delegated work to: %s.</p>')) % (
                escape(self.agent_id.display_name),
                Markup(', ').join(Markup('<b>%s</b>') % escape(agent.display_name) for agent in children.agent_id),
            )
            self.task_id.message_post(body=body, subject=_('Agent delegation created'))
        if self.task_id and skipped_agents:
            body = Markup(_('<p>Skipped mentioned agents without runtime: %s.</p>')) % (
                Markup(', ').join(Markup('<b>%s</b>') % escape(agent.display_name) for agent in skipped_agents)
            )
            self.task_id.message_post(body=body, subject=_('Agent delegation skipped'))
        return children

    def _build_delegated_prompt(self, agent):
        self.ensure_one()
        return _(
            'You were mentioned from execution "%(execution)s" by agent "%(agent)s".\n\n'
            'Focus only on the part of the task that matches your role.\n\n'
            'Original prompt:\n%(prompt)s'
        ) % {
            'execution': self.display_name,
            'agent': self.agent_id.display_name,
            'prompt': self.prompt or '',
        }

    def _after_finished(self, task_message):
        self.ensure_one()
        self.agent_id._refresh_status_from_executions()
        self._sync_project_task_stage()
        if self.task_id:
            body = task_message if isinstance(task_message, Markup) else escape(task_message)
            if self.result:
                body += Markup('<p><b>Result:</b></p><pre style="white-space:pre-wrap">%s</pre>') % escape(self.result)
            self.task_id.message_post(body=body, subject=_('Agent execution finished'))
        self._notify_execution_event('execution_updated')

    def _create_chat_reply(self, result=None):
        self.ensure_one()
        if self.source != 'chat' or not result:
            return self.env['odoo.agent.chat.message']
        existing = self.env['odoo.agent.chat.message'].search([
            ('execution_id', '=', self.id),
            ('author_type', '=', 'agent'),
        ], limit=1)
        if existing:
            return existing
        if self.chat_message_id:
            self.chat_message_id.delivery_state = 'delivered'
        return self.env['odoo.agent.chat.message'].sudo().send_agent_message(
            self.agent_id.id,
            result,
            project_task_id=self.task_id.id,
            execution_id=self.id,
            author_id=self.requested_by_id.id,
        )

    def _mark_chat_failed(self):
        self.ensure_one()
        if self.source == 'chat' and self.chat_message_id:
            self.chat_message_id.delivery_state = 'failed'

    def _notify_execution_event(self, event_name):
        self.ensure_one()
        payload = {
            'event': event_name,
            'execution_id': self.id,
            'status': self.status,
            'agent_id': self.agent_id.id,
            'runtime_id': self.runtime_id.id,
            'source': self.source,
            'chat_message_id': self.chat_message_id.id if self.chat_message_id else None,
            'task_id': self.task_id.id if self.task_id else None,
        }
        self.env['bus.bus']._sendone(f'odoo_agent.execution.{self.id}', 'odoo_agent', payload)
        self.env['bus.bus']._sendone(f'odoo_agent.agent.{self.agent_id.id}', 'odoo_agent', payload)
        if self.task_id:
            self.env['bus.bus']._sendone(f'odoo_agent.project_task.{self.task_id.id}', 'odoo_agent', payload)

    def _sync_project_task_stage(self):
        self.ensure_one()
        if not self.task_id:
            return
        stage = self.env['odoo.agent.stage.map'].get_stage_for_status(
            self.status,
            company_id=self.company_id.id,
            project=self.task_id.project_id,
        )
        if stage:
            self.task_id.stage_id = stage.id

    def to_runtime_payload(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'prompt': self.prompt or self.task_id.description or '',
            'status': self.status,
            'attempt': self.attempt,
            'source': self.source,
            'chat_message_id': self.chat_message_id.id if self.chat_message_id else None,
            'timeout_seconds': self.timeout_seconds,
            'retry_limit': self.retry_limit,
            'project_id': self.project_id.id if self.project_id else None,
            'task_id': self.task_id.id if self.task_id else None,
            'parent_execution_id': self.parent_id.id if self.parent_id else None,
            'child_execution_ids': self.child_ids.ids,
            'mentioned_agents': [
                {
                    'id': agent.id,
                    'name': agent.name,
                    'mention_key': agent.mention_key,
                }
                for agent in self.mentioned_agent_ids
            ],
            'created_at': fields.Datetime.to_string(self.create_date) if self.create_date else None,
            'conversation': self._conversation_runtime_payload(),
            'agent': self.agent_id.to_runtime_config(),
        }

    def _conversation_runtime_payload(self):
        self.ensure_one()
        if self.source != 'chat':
            return []
        domain = [('agent_id', '=', self.agent_id.id)]
        if self.task_id:
            domain.append(('project_task_id', '=', self.task_id.id))
        messages = self.env['odoo.agent.chat.message'].sudo().search(
            domain,
            order='timestamp desc, id desc',
            limit=20,
        )
        return [
            message.to_runtime_payload()
            for message in reversed(messages)
        ]

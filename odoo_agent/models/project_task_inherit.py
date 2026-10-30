# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.tools import html2plaintext


class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'odoo.agent.mixin']

    execution_ids = fields.One2many(
        'odoo.agent.execution',
        'task_id',
        string='Agent Executions',
    )
    latest_execution_id = fields.Many2one(
        'odoo.agent.execution',
        string='Latest Agent Execution',
        ondelete='set null',
        copy=False,
        check_company=True,
    )
    latest_execution_status = fields.Selection(
        related='latest_execution_id.status',
        string='Latest Agent Status',
        readonly=True,
    )
    execution_count = fields.Integer(
        string='Agent Execution Count',
        compute='_compute_execution_count',
    )
    agent_task_id = fields.Many2one(
        'odoo.agent.task',
        string='Legacy Agent Task',
        ondelete='set null',
        copy=False,
        help='Legacy tracking field. New flows use Agent Executions.',
    )
    agent_status = fields.Selection(
        related='latest_execution_id.status',
        string='Agent Status',
        readonly=True,
    )
    agent_chat_message_ids = fields.One2many(
        'odoo.agent.chat.message',
        'project_task_id',
        string='Agent Communications',
    )
    agent_chat_message_count = fields.Integer(
        string='Agent Communication Count',
        compute='_compute_agent_chat_message_count',
    )
    agent_chat_composer_agent_id = fields.Many2one(
        'odoo.agent',
        string='Message Agent',
        check_company=True,
        help='Agent that will receive the next task communication.',
    )
    agent_chat_composer_body = fields.Text(
        string='Message',
        help='Message to send to the selected agent in this task context.',
    )

    @api.depends('execution_ids')
    def _compute_execution_count(self):
        for task in self:
            task.execution_count = len(task.execution_ids)

    @api.depends('agent_chat_message_ids')
    def _compute_agent_chat_message_count(self):
        for task in self:
            task.agent_chat_message_count = len(task.agent_chat_message_ids)

    # ------------------------------------------------------------------
    # Mixin hooks
    # ------------------------------------------------------------------
    def _agent_backend_url(self):
        self.ensure_one()
        return f'{self.get_base_url()}/web#id={self.id}&model=project.task&view_type=form'

    def _agent_execution_prompt(self):
        self.ensure_one()
        parts = [self.name or '']
        if self.description:
            parts.append(html2plaintext(self.description).strip())
        return '\n\n'.join(part for part in parts if part)

    def _agent_context_payload(self):
        self.ensure_one()
        payload = super()._agent_context_payload()
        payload.update({
            'name': self.name,
            'description': html2plaintext(self.description or '').strip(),
            'project': self.project_id.display_name,
            'project_id': self.project_id.id,
            'stage': self.stage_id.display_name,
            'stage_id': self.stage_id.id,
            'priority': self.priority,
            'date_deadline': fields.Date.to_string(self.date_deadline) if self.date_deadline else None,
            'tags': self.tag_ids.mapped('name'),
            'assignees': self.user_ids.mapped('name'),
            'partner': self.partner_id.display_name if 'partner_id' in self._fields else None,
        })
        return payload

    def _prepare_agent_execution_vals(self, agent, prompt=None, source='task'):
        vals = super()._prepare_agent_execution_vals(agent, prompt=prompt, source=source)
        vals.update({
            'task_id': self.id,
            'project_id': self.project_id.id,
        })
        return vals

    # ------------------------------------------------------------------
    # Automatic dispatch
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks._agent_after_create()
        return tasks

    def write(self, vals):
        result = super().write(vals)
        self._agent_after_write(vals)
        if self.env.context.get('agent_skip_auto_dispatch'):
            return result
        stage_id = vals.get('stage_id')
        if stage_id:
            stage = self.env['project.task.type'].browse(stage_id)
            if stage.agent_auto_dispatch:
                self.filtered('agent_id')._dispatch_agent_execution(source='stage')
        return result

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        self._agent_hook_message_post(message)
        return message

    def action_assign_agent(self):
        return self.action_send_to_agent()

    # ------------------------------------------------------------------
    # Agent communications
    # ------------------------------------------------------------------
    def action_send_agent_chat_message(self):
        chat_model = self.env['odoo.agent.chat.message']
        for task in self:
            content = (task.agent_chat_composer_body or '').strip()
            agent = task.agent_chat_composer_agent_id or task.agent_id
            message, execution = chat_model.create_user_execution(
                agent,
                content,
                project_task=task,
                name=_('Chat message to %(agent)s') % {
                    'agent': agent.display_name if agent else _('Agent'),
                },
            )
            task.latest_execution_id = execution.id
            task.agent_chat_composer_body = False
            if not task.agent_chat_composer_agent_id:
                task.agent_chat_composer_agent_id = agent.id
            task._agent_post(
                _('Agent communication queued for %s.') % agent.display_name,
                subject=_('Agent communication queued'),
            )
        return True

    def action_retry_agent_execution(self):
        self.ensure_one()
        if not self.latest_execution_id:
            return self.action_send_to_agent()
        execution = self.latest_execution_id.action_retry()
        self.latest_execution_id = execution.id
        return True

    def action_cancel_agent_execution(self):
        for task in self:
            if task.latest_execution_id:
                task.latest_execution_id.action_request_cancel()
        return True

    def action_view_agent_logs(self):
        self.ensure_one()
        execution_ids = self.execution_ids.ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agent Logs'),
            'res_model': 'odoo.agent.log',
            'view_mode': 'list,form',
            'domain': [('execution_id', 'in', execution_ids)],
            'context': {'default_execution_id': self.latest_execution_id.id},
        }

    def action_view_agent_executions(self):
        self.ensure_one()
        action = super().action_view_agent_executions()
        action['context'].update({
            'default_task_id': self.id,
            'default_project_id': self.project_id.id,
        })
        return action

    def action_view_agent_communications(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agent Communications'),
            'res_model': 'odoo.agent.chat.message',
            'view_mode': 'list,form',
            'domain': [('project_task_id', '=', self.id)],
            'context': {
                'default_project_task_id': self.id,
                'default_agent_id': self.agent_id.id,
            },
        }

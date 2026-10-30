# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

ACTIVE_EXECUTION_STATES = ('queued', 'running', 'waiting_input', 'cancel_requested')


class AgentMixin(models.AbstractModel):
    """Reusable AI agent integration for any ``mail.thread`` model.

    The mixin adds an assigned agent, execution helpers and chatter mentions.
    It deliberately does not override ``message_post``: each concrete model calls
    ``_agent_hook_message_post`` from its own override so the behaviour does not
    depend on the MRO order of the inherited mixins.
    """

    _name = 'odoo.agent.mixin'
    _description = 'AI Agent Mixin'

    agent_id = fields.Many2one(
        'odoo.agent',
        string='AI Agent',
        ondelete='set null',
        tracking=True,
        check_company=True,
        index=True,
        help='Assign this record to an AI agent to run it on an external runtime.',
    )
    agent_execution_count = fields.Integer(
        string='Agent Executions',
        compute='_compute_agent_execution_count',
    )
    agent_last_execution_status = fields.Char(
        string='Last Agent Status',
        compute='_compute_agent_last_execution_status',
    )
    agent_has_active_execution = fields.Boolean(
        string='Agent Working',
        compute='_compute_agent_last_execution_status',
    )

    # ------------------------------------------------------------------
    # Compute helpers
    # ------------------------------------------------------------------
    def _agent_execution_domain(self):
        self.ensure_one()
        domain = [('res_model', '=', self._name), ('res_id', '=', self.id)]
        if self._name == 'project.task':
            # Executions created before res_model/res_id existed only carry task_id.
            domain = [
                '|',
                ('task_id', '=', self.id),
                '&', ('res_model', '=', self._name), ('res_id', '=', self.id),
            ]
        return domain

    @api.depends('agent_id')
    def _compute_agent_execution_count(self):
        Execution = self.env['odoo.agent.execution'].sudo()
        for record in self:
            record.agent_execution_count = Execution.search_count(record._agent_execution_domain())

    @api.depends('agent_id')
    def _compute_agent_last_execution_status(self):
        Execution = self.env['odoo.agent.execution'].sudo()
        for record in self:
            execution = Execution.search(record._agent_execution_domain(), order='id desc', limit=1)
            record.agent_last_execution_status = execution.status if execution else False
            record.agent_has_active_execution = bool(execution) and execution.status in ACTIVE_EXECUTION_STATES

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def _agent_company(self):
        self.ensure_one()
        return self.company_id if 'company_id' in self._fields and self.company_id else self.env.company

    def _agent_context_payload(self):
        """Return the record payload sent to the runtime.

        Concrete models override this to add their own business fields.
        """
        self.ensure_one()
        return {
            'model': self._name,
            'id': self.id,
            'display_name': self.display_name,
            'url': self._agent_backend_url(),
            'attachments': self._agent_attachment_payload(),
        }

    def _agent_backend_url(self):
        self.ensure_one()
        return f'{self.get_base_url()}/web#id={self.id}&model={self._name}&view_type=form'

    def _agent_attachment_payload(self):
        self.ensure_one()
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
        ], limit=50)
        return [
            {
                'id': attachment.id,
                'name': attachment.name,
                'mimetype': attachment.mimetype,
                'file_size': attachment.file_size,
                'checksum': attachment.checksum,
            }
            for attachment in attachments
        ]

    def _agent_execution_prompt(self):
        """Default prompt for a record. Concrete models override it."""
        self.ensure_one()
        parts = [self.display_name or '']
        description = getattr(self, 'description', False) or getattr(self, 'note', False)
        if description:
            parts.append(html2plaintext(description).strip())
        return '\n\n'.join(part for part in parts if part)

    def _prepare_agent_execution_vals(self, agent, prompt=None, source='task'):
        self.ensure_one()
        company = self._agent_company()
        return {
            'name': self.display_name or _('Agent execution'),
            'prompt': prompt if prompt is not None else self._agent_execution_prompt(),
            'agent_id': agent.id,
            'runtime_id': agent.runtime_id.id,
            'requested_by_id': self.env.user.id,
            'company_id': company.id,
            'source': source,
            'res_model': self._name,
            'res_id': self.id,
        }

    def _has_active_agent_execution(self, agent=None):
        self.ensure_one()
        domain = self._agent_execution_domain() + [('status', 'in', ACTIVE_EXECUTION_STATES)]
        if agent:
            domain.append(('agent_id', '=', agent.id))
        return bool(self.env['odoo.agent.execution'].sudo().search_count(domain))

    def _dispatch_agent_execution(self, agent=None, prompt=None, source='task', force=False):
        """Queue one execution for this record and return it.

        ``force`` bypasses the active execution guard and is reserved for the
        explicit "Send to agent" button.
        """
        self.ensure_one()
        agent = agent or self.agent_id
        if not agent:
            raise UserError(_('Assign an AI agent before sending the record.'))
        if not agent.runtime_id:
            raise UserError(_('The selected AI agent must have a runtime.'))
        if not force and self._has_active_agent_execution(agent):
            _logger.info(
                'Skipping dispatch for %s,%s: agent %s already has an active execution',
                self._name, self.id, agent.display_name,
            )
            return self.env['odoo.agent.execution']
        vals = self._prepare_agent_execution_vals(agent, prompt=prompt, source=source)
        return self.env['odoo.agent.execution'].create(vals)

    def action_send_to_agent(self):
        for record in self:
            if not record.agent_id:
                raise UserError(_('Assign an AI agent before sending the record.'))
            record._dispatch_agent_execution(force=True)
        return True

    def _agent_after_create(self):
        if self.env.context.get('agent_skip_auto_dispatch'):
            return
        for record in self:
            if record.agent_id and record.agent_id.dispatch_on_assign:
                record._dispatch_agent_execution()

    def _agent_after_write(self, vals):
        if self.env.context.get('agent_skip_auto_dispatch'):
            return
        if not vals.get('agent_id'):
            return
        for record in self:
            if record.agent_id and record.agent_id.dispatch_on_assign:
                record._dispatch_agent_execution()

    # ------------------------------------------------------------------
    # Chatter mentions
    # ------------------------------------------------------------------
    def _agent_hook_message_post(self, message):
        """Detect @mentions in a posted message and queue agent executions."""
        if not message or self.env.context.get('agent_skip_mentions'):
            return self.env['odoo.agent.execution']
        body = html2plaintext(message.body or '').strip()
        if '@' not in body:
            return self.env['odoo.agent.execution']
        if not self.env.user.has_group('base.group_user'):
            # Portal and public users must never wake an internal agent.
            return self.env['odoo.agent.execution']
        tokens = re.findall(r'@([A-Za-z0-9_.-]+)', body)
        if not tokens:
            return self.env['odoo.agent.execution']
        company = self._agent_company()
        agents = self.env['odoo.agent'].sudo().resolve_mention_tokens(tokens, company=company)
        author = message.author_id
        agents = agents.filtered(
            lambda agent: not agent.user_id or agent.user_id.partner_id != author
        )
        executions = self.env['odoo.agent.execution']
        for record in self:
            for agent in agents.filtered('runtime_id'):
                execution = record._dispatch_agent_execution(
                    agent=agent, prompt=body, source='mention',
                )
                executions |= execution
        if not executions and agents:
            self._agent_post_skipped_mention(agents)
        return executions

    def _agent_post_skipped_mention(self, agents):
        self.ensure_one()
        body = Markup(_('<p>Mentioned agents without runtime were skipped: %s.</p>')) % (
            Markup(', ').join(Markup('<b>%s</b>') % escape(agent.display_name) for agent in agents)
        )
        self.message_post(body=body, subject=_('Agent mention skipped'))

    def _agent_post(self, body, subject=None, author=None):
        """Post a message in the record chatter without waking agents again."""
        self.ensure_one()
        if not hasattr(self, 'message_post'):
            return None
        return self.sudo().with_context(agent_skip_mentions=True).message_post(
            body=body, subject=subject, author_id=author.id if author else None,
        )

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def action_view_agent_executions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'odoo_agent.action_agent_execution'
        )
        action['domain'] = self._agent_execution_domain()
        action['context'] = {
            'default_agent_id': self.agent_id.id,
            'default_res_model': self._name,
            'default_res_id': self.id,
        }
        return action

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import html2plaintext

from .common import AgentTestMixin


@tagged('post_install', '-at_install')
class TestProjectTaskAgentFlow(AgentTestMixin):

    def test_send_to_agent_creates_execution_from_project_task(self):
        self.task.action_send_to_agent()

        execution = self.task.latest_execution_id
        self.assertTrue(execution)
        self.assertEqual(execution.task_id, self.task)
        self.assertEqual(execution.project_id, self.project)
        self.assertEqual(execution.agent_id, self.agent)
        self.assertEqual(execution.runtime_id, self.runtime)
        self.assertIn(self.task.name, execution.prompt)
        self.assertIn(html2plaintext(self.task.description or '').strip(), execution.prompt)

    def test_project_task_html_description_becomes_plain_prompt(self):
        self.task.description = (
            '<p>Validate deployment strategy.</p>'
            '<ul><li>Check healthchecks</li><li>Check rollback</li></ul>'
        )

        self.task.action_send_to_agent()

        prompt = self.task.latest_execution_id.prompt
        self.assertIn('Validate deployment strategy.', prompt)
        self.assertIn('Check healthchecks', prompt)
        self.assertIn('Check rollback', prompt)
        self.assertNotIn('<p>', prompt)
        self.assertNotIn('<li>', prompt)

    def test_legacy_agent_task_description_is_stored_as_plain_text(self):
        legacy_task = self.env['odoo.agent.task'].create({
            'name': 'Legacy HTML task',
            'description': '<p>Validate portal.</p><p>Check rollback.</p>',
            'agent_id': self.agent.id,
            'project_id': self.project.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        self.assertIn('Validate portal.', legacy_task.description)
        self.assertIn('Check rollback.', legacy_task.description)
        self.assertNotIn('<p>', legacy_task.description)

    def test_send_to_agent_requires_agent_and_runtime(self):
        task_without_agent = self.env['project.task'].create({
            'name': 'No Agent Task',
            'project_id': self.project.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(UserError):
            task_without_agent.action_send_to_agent()

        self.agent.runtime_id = False
        with self.assertRaises(UserError):
            self.task.action_send_to_agent()

    def test_cancel_latest_execution_requests_cancellation(self):
        self.task.action_send_to_agent()
        self.task.action_cancel_agent_execution()

        self.assertEqual(self.task.latest_execution_id.status, 'cancel_requested')
        self.assertTrue(self.task.latest_execution_id.cancellation_reason)

    def test_view_logs_action_is_scoped_to_task_executions(self):
        self.task.action_send_to_agent()
        action = self.task.action_view_agent_logs()

        self.assertEqual(action['res_model'], 'odoo.agent.log')
        self.assertIn(('execution_id', 'in', self.task.execution_ids.ids), action['domain'])

    def test_task_agent_communication_creates_chat_execution(self):
        self.task.agent_chat_composer_body = 'Can you review the acceptance criteria?'

        # Explicit language: _() falls back to the user's language otherwise.
        self.task.with_context(lang='en_US').action_send_agent_chat_message()

        message = self.task.agent_chat_message_ids[0]
        execution = message.execution_id
        self.assertEqual(message.project_task_id, self.task)
        self.assertEqual(message.agent_id, self.agent)
        self.assertEqual(message.author_type, 'user')
        self.assertEqual(message.delivery_state, 'queued')
        self.assertEqual(execution.source, 'chat')
        self.assertEqual(execution.task_id, self.task)
        self.assertEqual(execution.chat_message_id, message)
        self.assertEqual(execution.name, 'Chat message to %s' % self.agent.display_name)
        self.assertNotIn(self.task.display_name, execution.name)
        self.assertEqual(self.task.latest_execution_id, execution)
        self.assertFalse(self.task.agent_chat_composer_body)

    def test_task_agent_communication_requires_body(self):
        with self.assertRaises(UserError):
            self.task.action_send_agent_chat_message()

    def test_task_agent_communication_action_is_scoped_to_task(self):
        action = self.task.action_view_agent_communications()

        self.assertEqual(action['res_model'], 'odoo.agent.chat.message')
        self.assertIn(('project_task_id', '=', self.task.id), action['domain'])

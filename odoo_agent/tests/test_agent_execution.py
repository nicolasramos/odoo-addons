# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from .common import AgentTestMixin


@tagged('post_install', '-at_install')
class TestAgentExecution(AgentTestMixin):

    def test_execution_payload_contains_runtime_configuration(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Payload Test',
            'prompt': 'Use the new execution prompt.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        payload = execution.to_runtime_payload()

        self.assertEqual(payload['id'], execution.id)
        self.assertEqual(payload['prompt'], 'Use the new execution prompt.')
        self.assertEqual(payload['agent']['engine'], 'hermes')
        self.assertEqual(payload['agent']['cli_command'], 'hermes run --context {instruction}')
        self.assertEqual(payload['agent']['skills'][0]['name'], self.skill.name)
        self.assertEqual(payload['agent']['mcp_servers'][0]['key'], self.mcp_server.server_key)

    def test_chat_execution_payload_contains_conversation(self):
        message = self.env['odoo.agent.chat.message'].send_user_message(
            self.agent.id,
            'Can you review this task?',
            project_task_id=self.task.id,
        )
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Chat Test',
            'prompt': message.content,
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
            'source': 'chat',
            'chat_message_id': message.id,
        })
        message.execution_id = execution.id

        payload = execution.to_runtime_payload()

        self.assertEqual(payload['source'], 'chat')
        self.assertEqual(payload['chat_message_id'], message.id)
        self.assertTrue(payload['conversation'])
        self.assertEqual(payload['conversation'][-1]['content'], message.content)

    def test_execution_lifecycle_updates_agent_and_task(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Lifecycle Test',
            'prompt': 'Run lifecycle.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        self.assertEqual(execution.status, 'queued')
        self.assertEqual(self.task.latest_execution_id, execution)

        execution.action_start()
        self.assertEqual(execution.status, 'running')
        self.assertEqual(self.agent.status, 'working')

        execution.action_complete(result='Lifecycle completed.')
        self.assertEqual(execution.status, 'completed')
        self.assertEqual(execution.result, 'Lifecycle completed.')
        self.assertEqual(self.agent.status, 'idle')

    def test_chat_execution_completion_creates_agent_reply(self):
        message = self.env['odoo.agent.chat.message'].send_user_message(
            self.agent.id,
            'Please answer from the runtime.',
            project_task_id=self.task.id,
        )
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Chat Reply Test',
            'prompt': message.content,
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
            'source': 'chat',
            'chat_message_id': message.id,
        })
        message.execution_id = execution.id

        execution.action_complete(result='Runtime answer.')

        agent_reply = self.env['odoo.agent.chat.message'].search([
            ('execution_id', '=', execution.id),
            ('author_type', '=', 'agent'),
        ])
        self.assertEqual(len(agent_reply), 1)
        self.assertEqual(agent_reply.content, 'Runtime answer.')
        self.assertEqual(message.delivery_state, 'delivered')

    def test_bus_notifications_are_sent_for_chat_log_and_execution(self):
        calls = []
        bus = self.env['bus.bus']
        bus_type = type(bus)
        had_own_sendone = '_sendone' in bus_type.__dict__
        original = bus_type._sendone

        def patched_sendone(record, target, notification_type, message):
            calls.append((target, notification_type, message))
            return original(record, target, notification_type, message)

        bus_type._sendone = patched_sendone
        try:
            message = self.env['odoo.agent.chat.message'].send_user_message(
                self.agent.id,
                'Notify me.',
                project_task_id=self.task.id,
            )
            execution = self.env['odoo.agent.execution'].create({
                'name': 'Bus Test',
                'prompt': 'Notify me.',
                'agent_id': self.agent.id,
                'task_id': self.task.id,
                'company_id': self.company.id,
                'source': 'chat',
                'chat_message_id': message.id,
            })
            self.env['odoo.agent.log'].create({
                'execution_id': execution.id,
                'level': 'info',
                'message': 'Live log.',
            })
            execution.action_start()
        finally:
            if had_own_sendone:
                bus_type._sendone = original
            else:
                delattr(bus_type, '_sendone')

        event_names = {call[2].get('event') for call in calls if call[1] == 'odoo_agent'}
        self.assertIn('chat_message_created', event_names)
        self.assertIn('log_created', event_names)
        self.assertIn('execution_updated', event_names)
        targets = {call[0] for call in calls}
        self.assertIn(f'odoo_agent.project_task.{self.task.id}', targets)

    def test_execution_retry_creates_child_attempt(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Retry Test',
            'prompt': 'Run retry.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })
        execution.action_fail(error_message='First attempt failed.')

        retry = execution.action_retry()

        self.assertEqual(retry.parent_id, execution)
        self.assertEqual(retry.attempt, execution.attempt + 1)
        self.assertEqual(retry.status, 'queued')
        self.assertEqual(retry.prompt, execution.prompt)

    def test_chatter_escapes_dynamic_result_content(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Chatter Test',
            'prompt': 'Run chatter.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        execution.action_complete(result='<script>alert("x")</script>')

        body = self.task.message_ids[:1].body
        self.assertIn('<b>Result:</b>', body)
        self.assertIn('&lt;script&gt;', body)
        self.assertNotIn('<script>alert', body)

    def test_prompt_mentions_create_child_executions(self):
        qa_agent = self.env['odoo.agent'].create({
            'name': 'QA Agent',
            'mention_key': 'qa',
            'runtime_id': self.runtime.id,
            'engine': 'opencode',
            'cli_command': 'opencode run {instruction}',
            'company_id': self.company.id,
        })

        execution = self.env['odoo.agent.execution'].create({
            'name': 'Mention Test',
            'prompt': 'Implement the feature and ask @qa to review edge cases.',
            'agent_id': self.agent.id,
            'runtime_id': self.runtime.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        self.assertIn(qa_agent, execution.mentioned_agent_ids)
        self.assertEqual(len(execution.child_ids), 1)
        self.assertEqual(execution.child_ids.agent_id, qa_agent)
        self.assertEqual(execution.child_ids.parent_id, execution)
        self.assertIn('Original prompt:', execution.child_ids.prompt)

    def test_child_execution_does_not_expand_mentions_again(self):
        qa_agent = self.env['odoo.agent'].create({
            'name': 'QA Loop Agent',
            'mention_key': 'qa-loop',
            'runtime_id': self.runtime.id,
            'engine': 'opencode',
            'cli_command': 'opencode run {instruction}',
            'company_id': self.company.id,
        })
        parent = self.env['odoo.agent.execution'].create({
            'name': 'Parent Mention',
            'prompt': 'Parent prompt.',
            'agent_id': self.agent.id,
            'runtime_id': self.runtime.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        child = self.env['odoo.agent.execution'].create({
            'name': 'Child Mention',
            'prompt': 'This child mentions @qa-loop but should not fan out.',
            'agent_id': self.agent.id,
            'runtime_id': self.runtime.id,
            'task_id': self.task.id,
            'parent_id': parent.id,
            'company_id': self.company.id,
        })

        self.assertIn(qa_agent, child.mentioned_agent_ids)
        self.assertFalse(child.child_ids)

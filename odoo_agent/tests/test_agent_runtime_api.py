# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestAgentRuntimeApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.runtime = cls.env['odoo.agent.runtime'].create({
            'name': 'API Runtime',
            'machine_id': 'api-runtime',
            'company_id': cls.company.id,
        })
        cls.runtime.action_generate_api_key()
        cls.other_runtime = cls.env['odoo.agent.runtime'].create({
            'name': 'Other API Runtime',
            'machine_id': 'other-api-runtime',
            'company_id': cls.company.id,
        })
        cls.other_runtime.action_generate_api_key()
        cls.agent = cls.env['odoo.agent'].create({
            'name': 'API Agent',
            'runtime_id': cls.runtime.id,
            'engine': 'opencode',
            'cli_command': 'opencode run {instruction}',
            'company_id': cls.company.id,
        })
        cls.execution = cls.env['odoo.agent.execution'].create({
            'name': 'API Execution',
            'prompt': 'API prompt',
            'agent_id': cls.agent.id,
            'runtime_id': cls.runtime.id,
            'company_id': cls.company.id,
        })

    def _json_request(self, path, api_key=None, payload=None, headers=None):
        request_headers = {'Content-Type': 'application/json'}
        request_headers.update(headers or {})
        if api_key:
            request_headers['X-API-Key'] = api_key
        response = self.url_open(
            path,
            data=json.dumps(payload or {}).encode(),
            headers=request_headers,
        )
        data = json.loads(response.content)
        return response.status_code, data

    def _form_request(self, path, payload=None):
        response = self.url_open(
            path,
            data=payload or {},
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        data = json.loads(response.content)
        return response.status_code, data

    def test_heartbeat_requires_valid_api_key(self):
        status, payload = self._json_request(
            '/api/agent/runtime/heartbeat',
            api_key='invalid',
        )
        self.assertEqual(status, 401)
        self.assertIn('error', payload)

    def test_heartbeat_accepts_api_key_header(self):
        status, payload = self._json_request(
            '/api/agent/runtime/heartbeat',
            api_key=self.runtime.api_key,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertEqual(payload.get('runtime_id'), self.runtime.id)

    def test_heartbeat_accepts_api_key_json_body(self):
        status, payload = self._json_request(
            '/api/agent/runtime/heartbeat',
            payload={'api_key': self.runtime.api_key},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertEqual(payload.get('runtime_id'), self.runtime.id)

    def test_heartbeat_accepts_api_key_form_body(self):
        status, payload = self._form_request(
            '/api/agent/runtime/heartbeat',
            payload={'api_key': self.runtime.api_key},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertEqual(payload.get('runtime_id'), self.runtime.id)

    def test_heartbeat_accepts_bearer_token(self):
        status, payload = self._json_request(
            '/api/agent/runtime/heartbeat',
            headers={'Authorization': f'Bearer {self.runtime.api_key}'},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertEqual(payload.get('runtime_id'), self.runtime.id)

    def test_heartbeat_strips_api_key_whitespace(self):
        status, payload = self._json_request(
            '/api/agent/runtime/heartbeat',
            api_key=f'  {self.runtime.api_key}  ',
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertEqual(payload.get('runtime_id'), self.runtime.id)

    def test_poll_returns_owned_execution_payload(self):
        status, payload = self._json_request(
            '/api/agent/runtime/poll',
            api_key=self.runtime.api_key,
            payload={'limit': 5},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertIn('executions', payload)
        if payload.get('executions'):
            self.assertEqual(payload['executions'][0]['id'], self.execution.id)

    def test_poll_excludes_tasks_by_default(self):
        status, payload = self._json_request(
            '/api/agent/runtime/poll',
            api_key=self.runtime.api_key,
            payload={'limit': 5},
        )
        self.assertEqual(status, 200)
        self.assertIn('executions', payload)
        self.assertNotIn('tasks', payload)

    def test_poll_includes_tasks_with_legacy_flag(self):
        status, payload = self._json_request(
            '/api/agent/runtime/poll?legacy_tasks=true',
            api_key=self.runtime.api_key,
            payload={'limit': 5},
        )
        self.assertEqual(status, 200)
        self.assertIn('executions', payload)
        self.assertIn('tasks', payload)
        self.assertEqual(payload['tasks'], payload['executions'])

    def test_cross_runtime_start_is_denied(self):
        status, payload = self._json_request(
            f'/api/agent/execution/{self.execution.id}/start',
            api_key=self.other_runtime.api_key,
        )
        self.assertEqual(status, 403)
        self.assertIn('error', payload)

    def test_log_requires_message(self):
        status, payload = self._json_request(
            f'/api/agent/execution/{self.execution.id}/log',
            api_key=self.runtime.api_key,
            payload={'level': 'info'},
        )
        self.assertEqual(status, 400)
        self.assertIn('error', payload)

    def test_runtime_can_post_execution_message(self):
        status, payload = self._json_request(
            f'/api/agent/execution/{self.execution.id}/message',
            api_key=self.runtime.api_key,
            payload={'message': 'Intermediate agent reply.'},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        message = self.env['odoo.agent.chat.message'].browse(payload['message_id'])
        self.assertEqual(message.execution_id, self.execution)
        self.assertEqual(message.author_type, 'agent')
        self.assertEqual(message.content, 'Intermediate agent reply.')

    def test_cross_runtime_message_is_denied(self):
        status, payload = self._json_request(
            f'/api/agent/execution/{self.execution.id}/message',
            api_key=self.other_runtime.api_key,
            payload={'message': 'Forbidden.'},
        )

        self.assertEqual(status, 403)
        self.assertIn('error', payload)

    def test_user_chat_creates_execution(self):
        self.authenticate('admin', 'admin')
        status, payload = self._json_request(
            f'/api/agent/{self.agent.id}/chat',
            payload={
                'message': 'Please handle this from chat.',
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload.get('status'), 'ok')
        self.assertTrue(payload.get('message_id'))
        self.assertTrue(payload.get('execution_id'))
        execution = self.env['odoo.agent.execution'].browse(payload['execution_id'])
        self.assertEqual(execution.source, 'chat')
        self.assertEqual(execution.chat_message_id.id, payload['message_id'])

    def test_user_chat_execution_accepts_integer_agent_id(self):
        message, execution = self.env['odoo.agent.chat.message'].create_user_execution(
            self.agent.id,
            'Please handle this XML-RPC chat message.',
        )

        self.assertEqual(message.agent_id, self.agent)
        self.assertEqual(execution.agent_id, self.agent)
        self.assertEqual(execution.chat_message_id, message)

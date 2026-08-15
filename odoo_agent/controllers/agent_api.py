# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging

from odoo import fields, http
from odoo.http import Response, request
from odoo.tools import html2plaintext


_logger = logging.getLogger(__name__)


class AgentApiController(http.Controller):

    def _payload(self):
        payload = dict(request.params or {})
        raw = request.httprequest.get_data(cache=True, as_text=True)
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload.update(parsed)
        json_request = getattr(request, 'jsonrequest', None)
        if isinstance(json_request, dict):
            payload.update(json_request)
        return payload

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, default=str),
            status=status,
            content_type='application/json',
        )

    def _error(self, message, status=400, code=None):
        data = {'status': 'error', 'error': message}
        if code:
            data['code'] = code
        return self._json_response(data, status=status)

    def _runtime_api_key_from_request(self):
        headers = request.httprequest.headers
        api_key = headers.get('X-API-Key') or headers.get('X-Odoo-Agent-Api-Key')

        if not api_key:
            authorization = headers.get('Authorization') or ''
            auth_scheme, _, auth_value = authorization.partition(' ')
            if auth_scheme.lower() in ('bearer', 'apikey', 'api-key'):
                api_key = auth_value

        if not api_key:
            form = request.httprequest.form or {}
            api_key = form.get('api_key') or form.get('token')

        if not api_key:
            json_request = getattr(request, 'jsonrequest', None)
            if isinstance(json_request, dict):
                api_key = json_request.get('api_key') or json_request.get('token')

        if not api_key:
            raw = request.httprequest.get_data(cache=True, as_text=True)
            if raw:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    api_key = parsed.get('api_key') or parsed.get('token')

        if api_key is None:
            return None
        return str(api_key).strip() or None

    def _authenticate_runtime(self):
        api_key = self._runtime_api_key_from_request()
        Runtime = request.env['odoo.agent.runtime'].sudo()
        if not api_key:
            return Runtime.browse()

        runtime = Runtime.search([('api_key', '=', api_key)], limit=1)
        if not runtime:
            _logger.warning(
                'Invalid Odoo Agent runtime API key on database %s from %s',
                request.env.cr.dbname,
                request.httprequest.remote_addr,
            )
        return runtime

    def _get_runtime_execution(self, runtime, execution_id):
        execution = request.env['odoo.agent.execution'].sudo().browse(execution_id)
        if not execution.exists():
            execution = self._get_or_create_execution_from_legacy_task(runtime, execution_id)
        if not execution or not execution.exists():
            return None, self._error('Execution not found', status=404, code='not_found')
        if execution.runtime_id.id != runtime.id:
            return None, self._error('Execution is not assigned to this runtime', status=403, code='forbidden')
        return execution, None

    def _get_or_create_execution_from_legacy_task(self, runtime, legacy_task_id):
        legacy_task = request.env['odoo.agent.task'].sudo().browse(legacy_task_id)
        if not legacy_task.exists():
            return request.env['odoo.agent.execution'].sudo()
        if legacy_task.agent_id.runtime_id.id != runtime.id:
            return request.env['odoo.agent.execution'].sudo()

        execution = request.env['odoo.agent.execution'].sudo().search([
            ('legacy_agent_task_id', '=', legacy_task.id),
        ], limit=1)
        if execution:
            return execution

        status_map = {
            'pending': 'queued',
            'in_progress': 'running',
            'completed': 'completed',
            'failed': 'failed',
            'cancelled': 'cancelled',
        }
        return request.env['odoo.agent.execution'].sudo().create({
            'name': legacy_task.name,
            'prompt': html2plaintext(legacy_task.description or '').strip(),
            'agent_id': legacy_task.agent_id.id,
            'runtime_id': legacy_task.agent_id.runtime_id.id,
            'project_id': legacy_task.project_id.id,
            'task_id': legacy_task.task_id.id,
            'legacy_agent_task_id': legacy_task.id,
            'status': status_map.get(legacy_task.status, 'queued'),
            'result': legacy_task.result,
            'error_message': legacy_task.error_message,
            'started_at': legacy_task.started_at,
            'completed_at': legacy_task.completed_at,
            'company_id': legacy_task.company_id.id or legacy_task.agent_id.company_id.id,
        })

    def _execution_logs_payload(self, execution, level=None, limit=100):
        domain = [('execution_id', '=', execution.id)]
        if level:
            domain.append(('level', '=', level))
        logs = request.env['odoo.agent.log'].sudo().search(domain, limit=limit)
        return [
            {
                'id': log.id,
                'timestamp': fields.Datetime.to_string(log.timestamp) if log.timestamp else None,
                'level': log.level,
                'message': log.message,
                'command': log.command,
                'exit_code': log.exit_code,
            }
            for log in logs
        ]

    @http.route('/api/agent/runtime/heartbeat', type='http', methods=['POST'], auth='public', csrf=False)
    def heartbeat(self, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        payload = self._payload()
        values = {
            'status': payload.get('status') if payload.get('status') in ('online', 'busy') else 'online',
            'last_seen': fields.Datetime.now(),
        }
        for field_name in ('version', 'device_info', 'ip_address', 'capabilities'):
            if field_name in payload:
                values[field_name] = payload.get(field_name)
        runtime.write(values)
        return self._json_response({
            'status': 'ok',
            'runtime_id': runtime.id,
            'runtime_name': runtime.name,
        })

    @http.route('/api/agent/runtime/capabilities', type='http', methods=['GET', 'POST'], auth='public', csrf=False)
    def capabilities(self, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        payload = self._payload()
        if request.httprequest.method == 'POST' and 'capabilities' in payload:
            runtime.write({'capabilities': payload.get('capabilities'), 'last_seen': fields.Datetime.now()})
        return self._json_response({
            'status': 'ok',
            'runtime': {
                'id': runtime.id,
                'name': runtime.name,
                'capabilities': runtime.capabilities,
            },
            'agents': [agent.to_runtime_config() for agent in runtime.agent_ids.filtered('active')],
        })

    @http.route('/api/agent/runtime/poll', type='http', methods=['GET', 'POST'], auth='public', csrf=False)
    def poll_executions(self, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        payload = self._payload()
        runtime.write({'last_seen': fields.Datetime.now()})
        limit = int(payload.get('limit') or 10)
        executions = request.env['odoo.agent.execution'].sudo().get_queued_for_runtime(runtime, limit=limit)
        response = {
            'status': 'ok',
            'executions': [execution.to_runtime_payload() for execution in executions],
        }
        # Compatibility: older runtimes still read the legacy ``tasks`` key.
        # Include it only when the client explicitly opts in (legacy_tasks=true).
        if payload.get('legacy_tasks') in (True, 'true', '1', 1):
            response['tasks'] = response['executions']
        return self._json_response(response)

    @http.route('/api/agent/execution/<int:execution_id>/start', type='http', methods=['POST'], auth='public', csrf=False)
    def start_execution(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        execution.action_start()
        return self._json_response({'status': 'ok', 'execution_id': execution.id, 'new_status': execution.status})

    @http.route('/api/agent/execution/<int:execution_id>/log', type='http', methods=['POST'], auth='public', csrf=False)
    def add_execution_log(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        payload = self._payload()
        message = payload.get('message')
        if not message:
            return self._error('message is required', status=400, code='validation_error')
        exit_code = payload.get('exit_code')
        log = request.env['odoo.agent.log'].sudo().create({
            'execution_id': execution.id,
            'level': payload.get('level') or 'info',
            'message': message,
            'command': payload.get('command'),
            'exit_code': int(exit_code) if exit_code not in (None, False, '') else False,
            'timestamp': fields.Datetime.now(),
        })
        execution.last_heartbeat_at = fields.Datetime.now()
        return self._json_response({'status': 'ok', 'log_id': log.id})

    @http.route('/api/agent/execution/<int:execution_id>/complete', type='http', methods=['POST'], auth='public', csrf=False)
    def complete_execution(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        payload = self._payload()
        execution.action_complete(result=payload.get('result'))
        return self._json_response({'status': 'ok', 'execution_id': execution.id, 'new_status': execution.status})

    @http.route('/api/agent/execution/<int:execution_id>/fail', type='http', methods=['POST'], auth='public', csrf=False)
    def fail_execution(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        payload = self._payload()
        execution.action_fail(error_message=payload.get('error_message') or payload.get('error'))
        return self._json_response({'status': 'ok', 'execution_id': execution.id, 'new_status': execution.status})

    @http.route('/api/agent/execution/<int:execution_id>/cancel', type='http', methods=['POST'], auth='public', csrf=False)
    def request_cancel_execution(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        execution.action_request_cancel()
        return self._json_response({'status': 'ok', 'execution_id': execution.id, 'new_status': execution.status})

    @http.route('/api/agent/execution/<int:execution_id>/cancel/ack', type='http', methods=['POST'], auth='public', csrf=False)
    def ack_cancel_execution(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        payload = self._payload()
        execution.action_ack_cancelled(reason=payload.get('reason'))
        return self._json_response({'status': 'ok', 'execution_id': execution.id, 'new_status': execution.status})

    @http.route('/api/agent/execution/<int:execution_id>/logs', type='http', methods=['GET'], auth='public', csrf=False)
    def get_execution_logs(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        payload = self._payload()
        logs = self._execution_logs_payload(
            execution,
            level=payload.get('level'),
            limit=int(payload.get('limit') or 100),
        )
        return self._json_response({'status': 'ok', 'logs': logs})

    @http.route('/api/agent/execution/<int:execution_id>/message', type='http', methods=['POST'], auth='public', csrf=False)
    def add_execution_message(self, execution_id, **kwargs):
        runtime = self._authenticate_runtime()
        if not runtime:
            return self._error('Invalid API key', status=401, code='invalid_api_key')
        execution, error = self._get_runtime_execution(runtime, execution_id)
        if error:
            return error
        payload = self._payload()
        content = payload.get('content') or payload.get('message')
        if not content:
            return self._error('message is required', status=400, code='validation_error')
        message = request.env['odoo.agent.chat.message'].sudo().send_agent_message(
            execution.agent_id.id,
            content,
            project_task_id=execution.task_id.id,
            execution_id=execution.id,
            author_id=execution.requested_by_id.id,
        )
        return self._json_response({'status': 'ok', 'message_id': message.id})

    # Compatibility routes for older runtimes that still call /task/{id}.
    @http.route('/api/agent/task/<int:task_id>/start', type='http', methods=['POST'], auth='public', csrf=False)
    def start_task(self, task_id, **kwargs):
        return self.start_execution(task_id, **kwargs)

    @http.route('/api/agent/task/<int:task_id>/complete', type='http', methods=['POST'], auth='public', csrf=False)
    def complete_task(self, task_id, **kwargs):
        payload = self._payload()
        if payload.get('status') == 'failed':
            return self.fail_execution(task_id, **kwargs)
        return self.complete_execution(task_id, **kwargs)

    @http.route('/api/agent/task/<int:task_id>/log', type='http', methods=['POST'], auth='public', csrf=False)
    def add_task_log(self, task_id, **kwargs):
        return self.add_execution_log(task_id, **kwargs)

    @http.route('/api/agent/task/<int:task_id>/logs', type='http', methods=['GET'], auth='public', csrf=False)
    def get_task_logs(self, task_id, **kwargs):
        return self.get_execution_logs(task_id, **kwargs)

    @http.route('/api/agent/runtime/register', type='http', methods=['POST'], auth='user', csrf=False)
    def register_runtime(self, **kwargs):
        if not request.env.user.has_group('odoo_agent.group_agent_admin'):
            return self._error('Only Agent Admin users can register runtimes', status=403, code='forbidden')
        payload = self._payload()
        name = payload.get('name')
        machine_id = payload.get('machine_id')
        if not name or not machine_id:
            return self._error('name and machine_id are required', status=400, code='validation_error')
        runtime = request.env['odoo.agent.runtime'].create({
            'name': name,
            'machine_id': machine_id,
            'ip_address': payload.get('ip_address'),
            'version': payload.get('version'),
            'device_info': payload.get('device_info'),
            'capabilities': payload.get('capabilities'),
            'company_id': request.env.company.id,
        })
        runtime.action_generate_api_key()
        return self._json_response({'status': 'ok', 'runtime_id': runtime.id, 'api_key': runtime.api_key})

    @http.route('/api/agent/<int:agent_id>/chat', type='http', methods=['POST'], auth='user', csrf=False)
    def send_chat_message(self, agent_id, **kwargs):
        payload = self._payload()
        content = payload.get('content') or payload.get('message')
        if not content:
            return self._error('content is required', status=400, code='validation_error')
        agent = request.env['odoo.agent'].browse(agent_id)
        if not agent.exists():
            return self._error('Agent not found', status=404, code='not_found')
        if not agent.runtime_id:
            return self._error('Agent has no runtime', status=400, code='validation_error')
        project_task = request.env['project.task'].browse(payload.get('project_task_id') or payload.get('task_id'))
        if project_task and not project_task.exists():
            return self._error('Project task not found', status=404, code='not_found')
        message, execution = request.env['odoo.agent.chat.message'].create_user_execution(
            agent,
            content,
            project_task=project_task if project_task else None,
            name=payload.get('name') or content[:80] or agent.display_name,
        )
        return self._json_response({
            'status': 'ok',
            'message_id': message.id,
            'execution_id': execution.id,
        })

    @http.route('/api/agent/<int:agent_id>/chat/messages', type='http', methods=['GET'], auth='user', csrf=False)
    def get_chat_messages(self, agent_id, **kwargs):
        payload = self._payload()
        messages = request.env['odoo.agent.chat.message'].get_conversation(
            agent_id,
            project_task_id=payload.get('project_task_id'),
            limit=int(payload.get('limit') or 50),
        )
        return self._json_response({
            'status': 'ok',
            'messages': [
                message.to_runtime_payload()
                for message in messages
            ],
        })

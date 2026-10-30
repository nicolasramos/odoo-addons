# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import AgentTestMixin


@tagged('post_install', '-at_install')
class TestAgentOrchestration(AgentTestMixin):

    def _new_task(self, **vals):
        base = {
            'name': 'Orchestration task',
            'project_id': self.project.id,
            'company_id': self.company.id,
        }
        base.update(vals)
        task = self.env['project.task'].with_context(agent_skip_auto_dispatch=True).create(base)
        # Return a clean context record so later writes honour the dispatch flags.
        return self.env['project.task'].browse(task.id)

    def _executions(self, task):
        return self.env['odoo.agent.execution'].search([
            ('res_model', '=', 'project.task'),
            ('res_id', '=', task.id),
        ])

    # ------------------------------------------------------------------
    # Stage mapping scope
    # ------------------------------------------------------------------
    def test_project_stage_mapping_wins_over_company_mapping(self):
        global_stage = self.env['project.task.type'].create({'name': 'Done (all)', 'sequence': 10})
        project_stage = self.env['project.task.type'].create({'name': 'Review (project)', 'sequence': 11})
        StageMap = self.env['odoo.agent.stage.map']
        StageMap.create({
            'agent_status': 'completed',
            'stage_id': global_stage.id,
            'company_id': self.company.id,
        })
        StageMap.create({
            'agent_status': 'completed',
            'stage_id': project_stage.id,
            'project_id': self.project.id,
            'company_id': self.company.id,
        })

        self.assertEqual(
            StageMap.get_stage_for_status('completed', self.company.id, self.project),
            project_stage,
        )
        other_project = self.env['project.project'].create({
            'name': 'Other project',
            'company_id': self.company.id,
        })
        self.assertEqual(
            StageMap.get_stage_for_status('completed', self.company.id, other_project),
            global_stage,
        )

    def test_unmapped_status_leaves_the_stage_untouched(self):
        original_stage = self.task.stage_id
        execution = self.env['odoo.agent.execution'].create({
            'name': 'No mapping',
            'prompt': 'Run without mapping.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        execution.action_complete(result='Done.')

        self.assertEqual(self.task.stage_id, original_stage)

    def test_completion_applies_project_stage_mapping(self):
        review = self.env['project.task.type'].create({'name': 'Review', 'sequence': 12})
        self.env['odoo.agent.stage.map'].create({
            'agent_status': 'completed',
            'stage_id': review.id,
            'project_id': self.project.id,
            'company_id': self.company.id,
        })
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Mapped',
            'prompt': 'Run mapped.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        execution.action_complete(result='Ready for review.')

        self.assertEqual(self.task.stage_id, review)

    # ------------------------------------------------------------------
    # Automatic dispatch
    # ------------------------------------------------------------------
    def test_assigning_agent_dispatches_one_execution(self):
        task = self._new_task()

        task.agent_id = self.agent
        task.agent_id = self.agent

        executions = self._executions(task)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions.source, 'task')
        self.assertEqual(executions.agent_id, self.agent)
        self.assertEqual(task.latest_execution_id, executions)

    def test_assigning_agent_with_dispatch_disabled_does_not_run(self):
        self.agent.dispatch_on_assign = False
        task = self._new_task()

        task.agent_id = self.agent

        self.assertFalse(self._executions(task))

    def test_entering_a_dispatch_stage_queues_the_agent(self):
        stage = self.env['project.task.type'].create({
            'name': 'In progress',
            'sequence': 13,
            'agent_auto_dispatch': True,
        })
        self.agent.dispatch_on_assign = False
        task = self._new_task(agent_id=self.agent.id)

        task.stage_id = stage

        executions = self._executions(task)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions.source, 'stage')

    def test_stage_sync_does_not_re_dispatch(self):
        stage = self.env['project.task.type'].create({
            'name': 'Review loop',
            'sequence': 14,
            'agent_auto_dispatch': True,
        })
        self.env['odoo.agent.stage.map'].create({
            'agent_status': 'completed',
            'stage_id': stage.id,
            'company_id': self.company.id,
        })
        self.agent.dispatch_on_assign = False
        task = self._new_task()
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Loop guard',
            'prompt': 'Run once.',
            'agent_id': self.agent.id,
            'task_id': task.id,
            'company_id': self.company.id,
        })

        execution.action_complete(result='Done.')

        self.assertEqual(task.stage_id, stage)
        self.assertEqual(len(self._executions(task)), 1)

    # ------------------------------------------------------------------
    # Runtime payload
    # ------------------------------------------------------------------
    def test_runtime_payload_includes_full_record_context(self):
        tag = self.env['project.tags'].create({'name': 'urgent'})
        task = self._new_task(description='<p>Ship the module.</p>', tag_ids=[(6, 0, tag.ids)])
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Context',
            'prompt': 'Ship it.',
            'agent_id': self.agent.id,
            'task_id': task.id,
            'company_id': self.company.id,
        })

        payload = execution.to_runtime_payload()

        self.assertEqual(payload['res_model'], 'project.task')
        self.assertEqual(payload['res_id'], task.id)
        self.assertEqual(payload['record']['name'], task.name)
        self.assertEqual(payload['record']['description'], 'Ship the module.')
        self.assertEqual(payload['record']['stage'], task.stage_id.display_name)
        self.assertEqual(payload['record']['tags'], ['urgent'])
        self.assertIn('url', payload['record'])

    # ------------------------------------------------------------------
    # Watchdog and retries
    # ------------------------------------------------------------------
    def test_stale_running_execution_is_failed_by_the_cron(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Stale',
            'prompt': 'Never finishes.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
            'timeout_seconds': 60,
        })
        execution.action_start()
        execution.write({'last_heartbeat_at': fields.Datetime.now() - timedelta(seconds=1200)})

        self.env['odoo.agent.execution']._cron_mark_stale()

        self.assertEqual(execution.status, 'failed')
        self.assertIn('heartbeat', execution.error_message)

    def test_failed_execution_retries_until_the_limit(self):
        self.agent.retry_limit = 1
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Retry me',
            'prompt': 'Fail once.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        execution.action_fail(error_message='boom')

        retry = self._executions(self.task).filtered(lambda e: e.parent_id == execution)
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry.attempt, 2)

    def test_completion_is_idempotent(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Idempotent',
            'prompt': 'Complete twice.',
            'agent_id': self.agent.id,
            'task_id': self.task.id,
            'company_id': self.company.id,
        })

        execution.action_complete(result='First.')
        messages = len(self.task.message_ids)
        execution.action_complete(result='Second.')

        self.assertEqual(execution.result, 'First.')
        self.assertEqual(len(self.task.message_ids), messages)

    # ------------------------------------------------------------------
    # Chatter mentions
    # ------------------------------------------------------------------
    def test_chatter_mention_dispatches_the_agent(self):
        self.agent.dispatch_on_assign = False
        task = self._new_task()

        task.message_post(body='@%s please review the acceptance criteria' % self.agent.mention_key)

        executions = self._executions(task)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions.source, 'mention')
        self.assertEqual(executions.agent_id, self.agent)
        self.assertIn('acceptance criteria', executions.prompt)

    def test_chatter_mention_without_handle_does_nothing(self):
        task = self._new_task()

        task.message_post(body='No agent mentioned here')

        self.assertFalse(self._executions(task))

    def test_agent_reply_does_not_trigger_another_execution(self):
        self.agent.dispatch_on_assign = False
        task = self._new_task()

        task._agent_post('@hermes the answer is 42')

        self.assertFalse(self._executions(task))

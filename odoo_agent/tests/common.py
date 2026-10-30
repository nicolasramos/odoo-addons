# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase


class AgentTestMixin(TransactionCase):
    """Shared records for Odoo Agent tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.runtime = cls.env['odoo.agent.runtime'].create({
            'name': 'Runtime Test Host',
            'machine_id': 'runtime-test-host',
            'company_id': cls.company.id,
        })
        cls.runtime.action_generate_api_key()
        cls.skill = cls.env['odoo.agent.skill'].create({
            'name': 'Test Skill',
            'instructions': 'Return concise, auditable output.',
            'category': 'analysis',
            'company_id': cls.company.id,
        })
        cls.mcp_server = cls.env['odoo.agent.mcp.server'].create({
            'name': 'Test MCP',
            'server_key': 'test-mcp',
            'transport': 'stdio',
            'command': 'python',
            'args': '-m test_server',
            'company_id': cls.company.id,
        })
        cls.agent = cls.env['odoo.agent'].create({
            'name': 'Hermes Test Agent',
            'runtime_id': cls.runtime.id,
            'engine': 'hermes',
            'cli_command': 'hermes run --context {instruction}',
            'instructions': 'Work only on the assigned task.',
            'skill_ids': [(6, 0, cls.skill.ids)],
            'mcp_server_ids': [(6, 0, cls.mcp_server.ids)],
            'company_id': cls.company.id,
        })
        cls.project = cls.env['project.project'].create({
            'name': 'Agent Test Project',
            'company_id': cls.company.id,
        })
        cls.task = cls.env['project.task'].with_context(agent_skip_auto_dispatch=True).create({
            'name': 'Agent Test Task',
            'description': 'Execute the test task.',
            'project_id': cls.project.id,
            'company_id': cls.company.id,
            'agent_id': cls.agent.id,
        })

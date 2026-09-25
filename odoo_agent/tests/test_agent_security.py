# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import AgentTestMixin


@tagged('post_install', '-at_install')
class TestAgentSecurity(AgentTestMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent_user_group = cls.env.ref('odoo_agent.group_agent_user')
        cls.agent_admin_group = cls.env.ref('odoo_agent.group_agent_admin')
        cls.agent_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Agent User',
            'login': 'agent-user@example.com',
            'email': 'agent-user@example.com',
            'group_ids': [(6, 0, [cls.agent_user_group.id])],
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
        })
        cls.regular_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Regular User',
            'login': 'regular-user@example.com',
            'email': 'regular-user@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
        })

    def test_agent_user_can_read_execution(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Security Read',
            'prompt': 'Read security.',
            'agent_id': self.agent.id,
            'runtime_id': self.runtime.id,
            'company_id': self.company.id,
        })

        self.assertEqual(execution.with_user(self.agent_user).name, 'Security Read')

    def test_regular_user_cannot_create_runtime(self):
        with self.assertRaises(AccessError):
            self.env['odoo.agent.runtime'].with_user(self.regular_user).create({
                'name': 'Denied Runtime',
                'machine_id': 'denied-runtime',
                'company_id': self.company.id,
            })

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import tagged

from odoo.addons.odoo_agent.tests.common import AgentTestMixin


@tagged('post_install', '-at_install')
class TestSaleOrderAgent(AgentTestMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Quotation Customer',
            'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Consulting hour',
            'type': 'service',
            'list_price': 100.0,
            'taxes_id': [(5, 0, 0)],
            'company_id': cls.company.id,
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'company_id': cls.company.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 2,
                'price_unit': 100.0,
            })],
        })

    def _executions(self):
        return self.env['odoo.agent.execution'].search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', self.order.id),
        ])

    def test_assigning_agent_to_a_quotation_dispatches(self):
        self.order.agent_id = self.agent

        executions = self._executions()
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions.source, 'task')
        self.assertEqual(executions.target_display_name, self.order.display_name)

    def test_quotation_mention_creates_an_execution(self):
        self.agent.dispatch_on_assign = False

        self.order.message_post(body='@%s review this quotation' % self.agent.mention_key)

        executions = self._executions()
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions.source, 'mention')

    def test_runtime_payload_contains_quotation_lines(self):
        execution = self.env['odoo.agent.execution'].create({
            'name': 'Quotation context',
            'prompt': 'Review the quotation.',
            'agent_id': self.agent.id,
            'res_model': 'sale.order',
            'res_id': self.order.id,
            'company_id': self.company.id,
        })

        payload = execution.to_runtime_payload()

        self.assertEqual(payload['record']['partner'], 'Quotation Customer')
        self.assertEqual(payload['record']['amount_untaxed'], 200.0)
        self.assertEqual(len(payload['record']['lines']), 1)
        self.assertEqual(payload['record']['lines'][0]['quantity'], 2)
        self.assertEqual(payload['record']['lines'][0]['subtotal'], 200.0)

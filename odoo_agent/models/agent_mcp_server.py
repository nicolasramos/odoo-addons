# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class AgentMcpServer(models.Model):
    _name = 'odoo.agent.mcp.server'
    _description = 'Agent MCP Server'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, index=True)
    server_key = fields.Char(string='Server Key', required=True, index=True)
    transport = fields.Selection(
        [
            ('stdio', 'stdio'),
            ('sse', 'SSE'),
            ('http', 'HTTP'),
        ],
        string='Transport',
        default='stdio',
        required=True,
    )
    command = fields.Char(string='Command')
    args = fields.Text(string='Arguments')
    url = fields.Char(string='URL')
    environment = fields.Text(string='Environment')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    agent_ids = fields.Many2many(
        'odoo.agent',
        'agent_mcp_server_rel',
        'mcp_server_id',
        'agent_id',
        string='Agents',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    _server_key_company_unique = models.Constraint(
        'unique(server_key, company_id)',
        "The MCP server key must be unique per company.",
    )

    def to_runtime_config(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'key': self.server_key,
            'transport': self.transport,
            'command': self.command,
            'args': self.args,
            'url': self.url,
            'environment': self.environment,
        }

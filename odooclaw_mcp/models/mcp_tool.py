from odoo import fields, models


class OdooclawMcpTool(models.Model):
    _name = "odooclaw.mcp.tool"
    _description = "OdooClaw MCP tool"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        help="Name exposed over MCP, lowercase with underscores, e.g. create_record.",
    )
    description = fields.Text(
        required=True,
        help="What the tool does and when to use it: the model reads this to choose it.",
    )
    model_name = fields.Char(
        help="Technical model the tool works on, e.g. res.partner. Used to list and to gate it.",
    )
    action_id = fields.Many2one(
        "ir.actions.server",
        required=True,
        ondelete="restrict",
        domain=[("state", "=", "code")],
        help="Server action that runs the tool. Its code reads the arguments from env.context['mcp_params'] and returns action = {...}.",
    )
    input_schema = fields.Text(
        default='{"type": "object", "properties": {}}',
        help="JSON Schema of the arguments, as the MCP client will see it.",
    )
    is_write = fields.Boolean(
        help="A write tool stays hidden and uncallable until 'Allow write tools' is enabled in Settings.",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

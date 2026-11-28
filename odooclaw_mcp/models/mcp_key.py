import secrets

from odoo import api, fields, models


class OdooclawMcpKey(models.Model):
    _name = "odooclaw.mcp.key"
    _description = "OdooClaw MCP key"
    _order = "name"

    name = fields.Char(required=True, help="Who uses this key and for what.")
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        help="The key acts as this user: Odoo applies their permissions and record rules.",
    )
    token = fields.Char(
        readonly=True,
        copy=False,
        index=True,
        groups="base.group_system",
        help="Secret presented in the X-MCP-Key header. It only opens /mcp, never the Odoo API.",
    )
    active = fields.Boolean(default=True)
    last_used_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("token"):
                vals["token"] = "mcp_" + secrets.token_urlsafe(32)
        return super().create(vals_list)

    def action_rotate(self):
        for key in self:
            key.token = "mcp_" + secrets.token_urlsafe(32)
        return True

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models, fields


class AccountDynamicRule(models.Model):
    _name = "account.dynamic.rule"
    _description = "Account Dynamic Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)

    # Match criteria
    partner_id = fields.Many2one("res.partner", string="Partner")
    product_id = fields.Many2one("product.product", string="Product")
    description_match = fields.Char(
        string="Description Match (Contains)",
        help="If set, relevant only if line description contains this text "
             "(case insensitive).",
    )

    # Actions
    account_id = fields.Many2one("account.account", string="Account")
    analytic_account_id = fields.Many2one(
        "account.analytic.account", string="Analytic Account"
    )
    target_product_id = fields.Many2one("product.product", string="Force Product")
    payment_term_id = fields.Many2one("account.payment.term", string="Payment Term")
    tax_ids = fields.Many2many(
        "account.tax",
        string="Taxes",
        help="Taxes to force on the invoice line when this rule matches.",
    )
    fiscal_position_id = fields.Many2one(
        "account.fiscal.position",
        string="Fiscal Position",
        help="Fiscal position to apply on the invoice when this rule matches.",
    )

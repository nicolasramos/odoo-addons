# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # API Defaults Logic (n8n/Imports)
            if 'partner_id' in vals and vals['partner_id']:
                partner = self.env['res.partner'].browse(vals['partner_id'])
                
                # 1. Payment Terms
                if not vals.get('invoice_payment_term_id') and partner.property_payment_term_id:
                    vals['invoice_payment_term_id'] = partner.property_payment_term_id.id
                
                # 2. Bank Account
                # Only for Purchase Invoices (Vendor Bills) -> Vendor Bank
                # For Sales Invoices, bank depends on Payment Mode or Company
                move_type = vals.get('move_type', self.env.context.get('default_move_type'))

                if move_type in ('in_invoice', 'in_refund', 'in_receipt') and not vals.get('partner_bank_id'):
                    if partner.bank_ids:
                        vals['partner_bank_id'] = partner.bank_ids[0].id

        return super().create(vals_list)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.model_create_multi
    def create(self, vals_list):
        # 1. Standard create
        lines = super().create(vals_list)

        # 2. Apply rules on created lines
        for line in lines:
            line._apply_dynamic_rules()
        
        return lines

    def _apply_dynamic_rules(self):
        """ Check if any rule matches and apply changes """
        self.ensure_one()
        # Only for purchase invoices (Vendor Bills and Refunds)
        if self.move_id.move_type not in ('in_invoice', 'in_refund'):
            return
        
        # Avoid touching non-accountable display lines
        if self.display_type in ('line_section', 'line_note'):
            return

        # Never apply dynamic rules on generated tax lines (VAT/Tax).
        # These lines must keep the account coming from tax repartition settings.
        if self.tax_line_id:
            return
        
        # Skip auto-generated lines (AP/AR, tax clearing, cash) — only touch expense/income accounts
        if self.account_id.account_type in (
            'liability_payable', 'asset_receivable',
            'liability_credit_card', 'asset_cash', 'liability_current',
        ):
            return
        
        # Helper to get partner (it might be on the move if not on the line)
        partner = self.partner_id or self.move_id.partner_id
        product = self.product_id

        # Find matching rules
        # Logic: 
        # 1. Partner must match OR be empty (Global)
        # 2. Product must match OR be empty (Global)
        # 3. Description (handled in loop below)
        domain = [
            ('partner_id', 'in', [partner.id, False]),
            ('product_id', 'in', [product.id, False]),
        ]
        
        rules = self.env['account.dynamic.rule'].search(domain, order='sequence')
        _logger.info("Dynamic Rules found: %s for Line %s", rules, self.name)

        for rule in rules:
            # check description match if set
            if rule.description_match:
                # Case insensitive check
                if not self.name or rule.description_match.lower() not in self.name.lower():
                    continue

            # If we reached here, the rule matches
            _logger.info("Applying Dynamic Rule: %s for Line %s", rule.name, self.name)

            # Apply Actions
            updates = {}
            if rule.account_id:
                updates['account_id'] = rule.account_id.id
            
            if rule.target_product_id:
                updates['product_id'] = rule.target_product_id.id

            if updates:
                self.write(updates)

            if rule.analytic_account_id:
                self.analytic_distribution = {str(rule.analytic_account_id.id): 100}
            
            if rule.payment_term_id and self.move_id:
                 # Update parent move payment term
                 self.move_id.write({'invoice_payment_term_id': rule.payment_term_id.id})

            # Apply taxes on the line (replace existing taxes)
            if rule.tax_ids:
                self.write({'tax_ids': [(6, 0, rule.tax_ids.ids)]})

            # Apply fiscal position on the move
            if rule.fiscal_position_id and self.move_id:
                self.move_id.write({'fiscal_position_id': rule.fiscal_position_id.id})

            # Apply only the first matching rule (highest priority/sequence)
            break

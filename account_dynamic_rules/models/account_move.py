# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


# --- API Defaults for imported invoices (n8n/webhooks) ---
class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-fill payment terms, bank account, and payment mode from Partner.

        This logic is scoped to import/API flows (n8n, webhooks) where callers
        send minimal invoice payloads. It does not affect UI-created invoices
        because the wizard already fills these fields.
        """
        for vals in vals_list:
            if 'partner_id' in vals and vals['partner_id']:
                partner = self.env['res.partner'].browse(vals['partner_id'])

                # 1. Payment Terms
                if not vals.get('invoice_payment_term_id') and partner.property_payment_term_id:
                    vals['invoice_payment_term_id'] = partner.property_payment_term_id.id

                # 2. Bank Account
                # Only for Purchase Invoices (Vendor Bills) -> Vendor Bank
                # For Sales Invoices, bank depends on Payment Mode or Company
                move_type = vals.get('move_type', self.env.context.get('default_move_type'))

                # 3. Payment Mode (requires account_payment_partner)
                if not vals.get('payment_mode_id'):
                    if move_type in ('in_invoice', 'in_refund', 'in_receipt') and hasattr(partner, 'supplier_payment_mode_id'):
                        if partner.supplier_payment_mode_id:
                            vals['payment_mode_id'] = partner.supplier_payment_mode_id.id
                    elif move_type in ('out_invoice', 'out_refund', 'out_receipt') and hasattr(partner, 'customer_payment_mode_id'):
                         if partner.customer_payment_mode_id:
                            vals['payment_mode_id'] = partner.customer_payment_mode_id.id

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
        """Apply dynamic rules on invoice line creation.

        Design decision: rules only run in `create`, not in `write`.
        Adding a `write` hook would risk infinite recursion — changing
        `account_id` or `product_id` triggers line recomputation, which
        calls `write` again. For the vast majority of workflows (imported
        vendor bills, API invoices), rules fire once at creation time,
        which is sufficient. Manual edits to an already-created line are
        rare and can be handled by re-creating the line if needed.
        """
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

        # Skip balance-sheet accounts — dynamic rules only target P&L lines
        # (expenses/income). This prevents accidental rewrites of auto-generated
        # AP/AR, cash, and credit-card lines that Odoo creates during invoice validation.
        if self.account_id.account_type in (
            'liability_payable',
            'asset_receivable',
            'liability_credit_card',
            'asset_cash',
            'liability_current',
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

        # Payment mode check (defensive)
        if hasattr(self.env['account.dynamic.rule'], 'payment_mode_id'):
            # Simplified: check move's payment_mode_id if exists
            payment_mode_id = self.move_id.payment_mode_id.id if hasattr(self.move_id, 'payment_mode_id') and self.move_id.payment_mode_id else False
            domain.append(('payment_mode_id', 'in', [payment_mode_id, False]))

        rules = self.env['account.dynamic.rule'].search(domain, order='sequence')
        _logger.info("Dynamic Rules found: %s for Line %s", rules, self.name)

        match_found = False
        for rule in rules:
            # check description match if set
            if rule.description_match:
                # Case insensitive check
                if not self.name or rule.description_match.lower() not in self.name.lower():
                    continue

            # If we reached here, the rule matches
            _logger.info("Applying Dynamic Rule: %s for Line %s", rule.name, self.name)
            match_found = True

            # Apply Actions
            updates = {}
            if rule.account_id:
                updates['account_id'] = rule.account_id.id

            if rule.target_product_id:
                updates['product_id'] = rule.target_product_id.id

            if updates:
                self.write(updates)

            # Odoo 17: use analytic_distribution (dict of plan_id -> percentage)
            if rule.analytic_account_id:
                distribution = dict(self.analytic_distribution or {})
                distribution[str(rule.analytic_account_id.plan_id.id)] = 100
                self.analytic_distribution = distribution

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

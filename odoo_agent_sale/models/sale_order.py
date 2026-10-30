# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.tools import html2plaintext


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'odoo.agent.mixin']

    def _agent_backend_url(self):
        self.ensure_one()
        return f'{self.get_base_url()}/web#id={self.id}&model=sale.order&view_type=form'

    def _agent_execution_prompt(self):
        self.ensure_one()
        parts = [self.display_name or '']
        if self.note:
            parts.append(html2plaintext(self.note).strip())
        lines = [
            _('- %(product)s x%(qty)s at %(price)s') % {
                'product': line.product_id.display_name or line.name,
                'qty': line.product_uom_qty,
                'price': line.price_unit,
            }
            for line in self.order_line[:20]
        ]
        if lines:
            parts.append('\n'.join(lines))
        return '\n\n'.join(part for part in parts if part)

    def _agent_context_payload(self):
        self.ensure_one()
        payload = super()._agent_context_payload()
        payload.update({
            'name': self.name,
            'partner': self.partner_id.display_name,
            'partner_id': self.partner_id.id,
            'state': self.state,
            'date_order': fields.Datetime.to_string(self.date_order) if self.date_order else None,
            'validity_date': fields.Date.to_string(self.validity_date) if self.validity_date else None,
            'amount_untaxed': self.amount_untaxed,
            'amount_tax': self.amount_tax,
            'amount_total': self.amount_total,
            'currency': self.currency_id.name,
            'note': html2plaintext(self.note or '').strip(),
            'lines': [
                {
                    'product': line.product_id.display_name,
                    'description': html2plaintext(line.name or '').strip(),
                    'quantity': line.product_uom_qty,
                    'unit_price': line.price_unit,
                    'discount': line.discount,
                    'subtotal': line.price_subtotal,
                }
                for line in self.order_line[:50]
            ],
        })
        return payload

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        self._agent_hook_message_post(message)
        return message

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._agent_after_create()
        return orders

    def write(self, vals):
        result = super().write(vals)
        self._agent_after_write(vals)
        return result

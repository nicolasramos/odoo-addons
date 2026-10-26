# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Accounting areas and counters for OdooClaw proactive assistance.

This module adds accounting-specific data to the proactive engine.
It depends on `account` so it only installs when Accounting is available.
"""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class MailOdooclawArea(models.Model):
    _inherit = "mail.odooclaw.area"

    def _count_with_today(self, model_name, domain):
        """Count records, resolving ``$today`` and ``$n_days_ago``."""
        if not domain:
            return 0

        def _resolve_placeholder(value):
            """Resolve placeholders recursively."""
            if isinstance(value, str):
                if value == "$today":
                    return fields.Date.context_today(self)
                if value.startswith("$") and "_days_ago" in value:
                    try:
                        n = int(value.split("_")[1])
                        return fields.Date.from_string(
                            fields.Date.context_today(self)
                        ) - relativedelta(days=n)
                    except (ValueError, IndexError):
                        return value
                return value
            if isinstance(value, list):
                return [_resolve_placeholder(v) for v in value]
            if isinstance(value, tuple):
                return tuple(_resolve_placeholder(v) for v in value)
            return value

        resolved_domain = [_resolve_placeholder(d) for d in domain]
        return self._count_records(model_name, resolved_domain)

    def _count_records(self, model_name, domain):
        """Count records matching a model + domain."""
        if not domain:
            return 0
        if model_name not in self.env:
            return 0
        try:
            if not isinstance(domain, (list, tuple)):
                return 0
            return self.env[model_name].sudo().search_count(domain)
        except Exception:  # noqa: BLE001 - a counter failure means silence
            _logger.warning(
                "odooclaw: could not count signal for area %s (model=%s)",
                self.area,
                model_name,
                exc_info=True,
            )
            return 0

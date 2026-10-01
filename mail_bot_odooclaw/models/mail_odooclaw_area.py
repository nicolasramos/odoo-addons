# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw proactive assistance.

Two pieces live here:

* ``/odooclaw/notify`` — the delivery endpoint. OdooClaw posts an UNSOLICITED
  offer here; this controller resolves the private bot chat for the target user
  and posts the message there. It is the only route in the module that writes
  without a human message behind it, so it is narrow, authenticated with the
  service secret (or the IP allowlist) and it can only ever target the bot's own
  private chat with a user — never a business record's chatter.

* ``mail.odooclaw.area`` — the mapping from an Odoo action/view to a functional
  area plus the deterministic counters for it. This is what makes the trigger
  independent of how the user phrases anything.

Why a separate endpoint and not ``/odooclaw/reply``: that route requires a
single-use ``reply_token`` that Odoo mints when a human writes to the bot, and
it validates that the reply is a direct answer. That gate is deliberate — it is
what makes ``sudo().message_post()`` safe there. Its direct consequence is that
a message nobody solicited cannot reach a business record's chatter through
that route.

The counters that power the offers live here too: they are deterministic — no
ML, no "confidence score" — so that when a user complains the assistant is
"suggesting the same thing every day", the answer is a number on a record, not
a guess.
"""

import json
import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class MailOdooclawArea(models.Model):
    """Mapping from an Odoo action to a proactive area.

    The area is the functional label the Go engine expects (``accounting``,
    ``sales``, etc.). The counters are the deterministic triggers that decide
    whether the area should offer help.

    Why this is a model instead of a static dict:
    * **It is a business rule.** "What counts as 'unreconciled'?" changes when
      the company changes its bank reconciliation process.
    * **It must be inspectable.** When the assistant is silent, someone needs to
      see the counters in the UI and understand why nothing triggered.
    * **The Go engine depends on the identifier.** Renaming one side without the
      other leaves the assistant mute with zero errors.
    """

    _name = "mail.odooclaw.area"
    _description = "OdooClaw proactive area"

    name = fields.Char(
        required=True,
        help="Human-readable label for this area.",
    )
    area = fields.Char(
        required=True,
        help="Functional area identifier. Must match what the Go engine "
        "expects in English: ``accounting``, ``sales``, etc.",
    )
    sequence = fields.Integer(
        default=100,
        help="Order in which areas are presented to the user.",
    )
    enabled = fields.Boolean(
        default=True,
        help="When disabled, this area never fires, even if the counters "
        "are non-zero.",
    )
    model_name = fields.Char(
        help="Primary model for this area. Used as a fallback when no "
        "action-specific row exists.",
    )
    signal_definition = fields.Text(
        help="JSON definition of the counters for the Go engine. "
        "Format: {\"counter_name\": {\"model\": \"model.name\", "
        "\"domain\": [...]}}, ...",
    )
    counters = fields.One2many(
        "mail.odooclaw.area.counter",
        "area_id",
        "Counters",
        help="Legacy counters. Use signal_definition for new areas.",
    )
    action_ids = fields.Many2many(
        "ir.actions.act_window",
        "mail_odooclaw_area_action_rel",
        "area_id",
        "action_id",
        "Actions",
        help="Actions that map to this area. When the user opens one of "
        "these actions, the area's counters are evaluated.",
    )

    @api.model
    def _count_with_today(self, model_name, domain):
        """Count records, resolving ``$today`` and ``$n_days_ago``.

        ``$today`` is replaced with today's date. ``$n_days_ago`` is
        replaced with today minus n days. This makes overdue counters
        self-updating without needing a cron job.

        Placeholder replacement happens at the leaf level, so a domain like
        ``["date_deadline", "<", "$today"]`` becomes
        ``["date_deadline", "<", "2026-10-01"]`` (or whatever today is).

        Overdue counters ("tasks past their deadline", "projects past their end
        date") need a moving reference. Hardcoding a date makes the counter
        silently rot: it keeps returning a number that is no longer meaningful,
        which is worse than returning nothing. ``$today`` is resolved at count
        time, so the counter always reflects today's perspective.

        ``$n_days_ago`` is resolved to the date n days before today and
        makes it possible to say "opportunities without activity in 30 days"
        without hardcoding a date or running a cron job.
        """
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
        """Count records matching a model + domain.

        This is the helper that makes every counter a one-liner.
        """
        if not domain:
            return 0

        # If the model is not installed (e.g., Contabilidad needs
        # `account`). That is not an error: it is an area that cannot apply yet,
        # and it must stay silent without logging a traceback on every view open.
        if model_name not in self.env:
            return 0

        try:
            # A malformed domain is a configuration mistake, not a crash.
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

    def counters_for(self, model_name=None):
        """Build the counters dict handed to the Go engine.

        The definition is looked up by model first (the view the user is on),
        falling back to any enabled area row when no model matched.
        """
        self.ensure_one()
        try:
            definitions = json.loads(self.signal_definition or "{}")
        except (TypeError, ValueError):
            _logger.warning(
                "odooclaw: invalid signal_definition JSON for area %s", self.area
            )
            return {}
        if not isinstance(definitions, dict):
            return {}

        counters = {}
        for key, definition in definitions.items():
            if not isinstance(definition, dict):
                continue
            model_name = definition.get("model")
            domain = definition.get("domain")
            if not model_name or not domain:
                continue
            count = self._count_with_today(model_name, domain)
            if count > 0:
                counters[key] = {
                    "count": count,
                    "model": model_name,
                    "domain": domain,
                }
        return counters

    def write(self, vals):
        if "area" in vals and vals["area"]:
            # Check for duplicates
            existing = self.search(
                [("area", "=", vals["area"]), ("id", "!=", self.id)]
            )
            if existing:
                raise ValidationError(
                    _("Area '%s' already exists.") % vals["area"]
                )
        return super().write(vals)

    def name_search(self, name, args=None, operator="ilike", limit=100):
        if not args:
            args = []
        if name:
            records = self.search(
                [("area", operator, name)] + args, limit=limit
            )
            if not records and operator == "ilike":
                records = self.search(
                    [("name", operator, name)] + args, limit=limit
                )
            return records.name_get()
        return super().name_search(name, args=args, operator=operator, limit=limit)


class MailOdooclawAreaCounter(models.Model):
    """A single deterministic counter for a proactive area.

    Every counter is a (model, domain) pair plus a human-readable label.
    When the counter is ``> 0`` the area is a candidate for offering help.
    """

    _name = "mail.odooclaw.area.counter"
    _description = "OdooClaw proactive area counter"

    area_id = fields.Many2one(
        "mail.odooclaw.area",
        required=True,
        ondelete="cascade",
    )
    trigger = fields.Char(
        required=True,
        help="Identifier for the Go engine. Must be in English.",
    )
    model_name = fields.Char(
        required=True,
        help="Odoo model to count, e.g. ``account.move``.",
    )
    domain = fields.Text(
        required=True,
        help="Domain as a string, e.g. "
        "'[\\\"state\\\", \\\"!=\\\", \\\"posted\\\"]'.",
    )
    name = fields.Char(
        compute="_compute_name",
        store=True,
        readonly=True,
    )

    @api.depends("trigger", "model_name")
    def _compute_name(self):
        for rec in self:
            rec.name = _("%(trigger)s (%(model)s)") % {
                "trigger": rec.trigger,
                "model": rec.model_name,
            }

    def _compute_count(self):
        """Evaluate the counter and return the count."""
        self.ensure_one()
        try:
            domain = safe_eval(self.domain)
        except Exception as exc:
            _logger.error(
                "odooclaw area: invalid domain %s: %s", self.domain, exc
            )
            return 0
        try:
            model = self.env[self.model_name].sudo()
            return model.search_count(domain)
        except AccessError:
            _logger.warning(
                "odooclaw area: AccessError on %s domain %s",
                self.model_name,
                self.domain,
            )
            return 0
        except Exception as exc:
            _logger.error(
                "odooclaw area: error on %s domain %s: %s",
                self.model_name,
                self.domain,
                exc,
            )
            return 0

    def name_search(self, name, args=None, operator="ilike", limit=100):
        if not args:
            args = []
        if name:
            records = self.search(
                [("trigger", operator, name)] + args, limit=limit
            )
            if not records:
                records = self.search(
                    [("name", operator, name)] + args, limit=limit
                )
            return records.name_get()
        return super().name_search(name, args=args, operator=operator, limit=limit)

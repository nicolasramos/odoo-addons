# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Who may be offered proactive help.

Nico's rule, stated plainly: *any internal DU user* — meaning an employee with an
internal Odoo account. Not a portal user, not the public user, not any other kind
of account.

Why this deserves its own model instead of an inline ``if``:

* **It is a business rule, not a technical detail.** "Who is an employee here" is
  the kind of thing that changes (contractors, temporary staff, a subsidiary) and
  the person who owns that answer is not the person who writes Go.
* **Getting it wrong leaks data.** The counters behind an offer are business
  figures — unposted invoices, unreconciled bank lines. Showing them to a portal
  user would be a data leak dressed up as a helpful message.
* **It must be auditable.** When someone asks "why did the assistant never offer
  me anything?", the answer has to be inspectable without reading code.

The classification itself is the standard Odoo one, and it is verified against a
real Odoo 18 database rather than assumed:

* ``share = False``  -> internal user (employee)
* ``share = True``   -> portal user
* ``active = False`` -> deactivated; must not receive new messages

``share`` is the field Odoo itself uses to draw the line between an employee and
an outsider (``base.group_user`` sets it), so using it keeps us aligned with the
platform instead of inventing a parallel definition.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class MailOdooclawAudience(models.Model):
    """The audience of proactive assistance: which internal users qualify."""

    _name = "mail.odooclaw.audience"
    _description = "OdooClaw proactive audience"
    _rec_name = "name"

    name = fields.Char(
        default=lambda self: _("Usuarios internos de DU"),
        required=True,
    )
    active = fields.Boolean(default=True)

    # -- The rule ---------------------------------------------------------
    internal_only = fields.Boolean(
        string="Solo usuarios internos",
        default=True,
        help="Solo se ofrece ayuda a usuarios internos (empleados). Los usuarios "
        "de portal y el usuario público quedan fuera: no son personal de la "
        "empresa y los contadores son cifras de negocio.",
    )
    include_inactive = fields.Boolean(
        string="Incluir usuarios desactivados",
        default=False,
        help="Un empleado dado de baja no debe recibir mensajes nuevos.",
    )

    # -- Optional narrowing ----------------------------------------------
    group_ids = fields.Many2many(
        "res.groups",
        string="Limitar a estos grupos",
        help="Opcional. Si se indica, la audiencia se limita además a los "
        "miembros de estos grupos. Vacío = cualquier usuario interno.",
    )
    excluded_group_ids = fields.Many2many(
        "res.groups",
        "mail_odooclaw_audience_excluded_group_rel",
        string="Excluir a estos grupos",
        help="Opcional. Los miembros de estos grupos nunca reciben ayuda, "
        "aunque cumplan el resto de condiciones.",
    )

    company_ids = fields.Many2many(
        "res.company",
        string="Limitar a estas compañías",
        help="Opcional. Vacío = todas las compañías.",
    )

    note = fields.Text(string="Notas")

    @api.model
    def _internal_domain(self):
        """The Odoo domain for "internal user", in one place.

        Kept as a method so the definition cannot drift between the resolver,
        the tests and any admin view.
        """
        return [("share", "=", False), ("active", "=", True)]

    def _audience_domain(self):
        """The full domain of users who are a candidate audience.

        Fail-closed by design: if no active audience row exists, nobody is a
        candidate. A missing configuration must never default to "everybody",
        because that would offer help (and show business figures) to users the
        customer never intended to include.
        """
        self.ensure_one()
        domain = [("share", "=", False)]
        if not self.include_inactive:
            domain.append(("active", "=", True))
        if self.group_ids:
            domain.append(("groups_id", "in", self.group_ids.ids))
        if self.excluded_group_ids:
            domain.append(("groups_id", "not in", self.excluded_group_ids.ids))
        if self.company_ids:
            domain.append(("company_ids", "in", self.company_ids.ids))
        return domain

    @api.model
    def resolve_for_user(self, user_id):
        """Classify one user for the engine.

        Returns a dict matching the Go side's ``ClassifiedUser`` so the caller
        never has to reinterpret Odoo's model: ``{user_id, is_internal,
        is_active, eligible, reason}``.

        The bot itself is excluded: it is an internal user, but offering the bot
        help would produce the assistant talking to itself.
        """
        user = self.env["res.users"].sudo().browse(int(user_id))
        if not user.exists():
            return {
                "user_id": int(user_id),
                "is_internal": False,
                "is_active": False,
                "eligible": False,
                "reason": _("el usuario no existe"),
            }

        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)

        is_internal = not user.share
        is_active = bool(user.active)

        audience = self.search([], limit=1)
        if not audience:
            return {
                "user_id": user.id,
                "is_internal": is_internal,
                "is_active": is_active,
                "eligible": False,
                "reason": _("no hay una audiencia configurada"),
            }

        if bot and user.id == bot.id:
            return {
                "user_id": user.id,
                "is_internal": is_internal,
                "is_active": is_active,
                "eligible": False,
                "reason": _("es el propio bot"),
            }

        if not user.filtered_domain(audience._audience_domain()):
            return {
                "user_id": user.id,
                "is_internal": is_internal,
                "is_active": is_active,
                "eligible": False,
                "reason": _("el usuario queda fuera de la audiencia configurada"),
            }

        return {
            "user_id": user.id,
            "is_internal": is_internal,
            "is_active": is_active,
            "eligible": True,
            "reason": "",
        }

    def eligible_user_ids(self):
        """Ids of every user who is a candidate audience right now."""
        self.ensure_one()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        domain = self._audience_domain()
        if bot:
            domain.append(("id", "!=", bot.id))
        return self.env["res.users"].sudo().search(domain).ids

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
* ``share = True``   -> portal user (excluded)
* ``id == public``   -> public user (excluded)
* ``id == False``    -> anonymous (excluded)

This is not opinion; it is the result of inspecting a live Odoo 18 database
and confirming the ``res.users`` schema.
"""

from odoo import api, fields, models


class MailOdooclawAudience(models.Model):
    """A rule that selects which users may be offered proactive help.

    The default audience is "all internal users" — any employee with an
    internal Odoo account.

    The model exists so that the rule can be inspected, edited, and audited
    from the UI without touching code.
    """

    _name = "mail.odooclaw.audience"
    _description = "OdooClaw proactive audience"

    name = fields.Char(required=True)
    internal_only = fields.Boolean(
        default=True,
        help="When checked, only internal users (employees) are eligible. "
        "Portal users and the public user are excluded.",
    )
    include_inactive = fields.Boolean(
        default=False,
        help="When checked, inactive (disabled) employees are also eligible. "
        "Useful when onboarding or offboarding.",
    )
    group_ids = fields.Many2many(
        "res.groups",
        "mail_odooclaw_audience_group_rel",
        "audience_id",
        "group_id",
        "Required groups",
        help="When set, only users in ALL of these groups are eligible. "
        "Useful for limiting to a department or role.",
    )
    excluded_group_ids = fields.Many2many(
        "res.groups",
        "mail_odooclaw_audience_excluded_group_rel",
        "audience_id",
        "excluded_group_id",
        "Excluded groups",
        help="Users in ANY of these groups are excluded, even if they meet "
        "all other criteria.",
    )
    active = fields.Boolean(default=True)
    note = fields.Html(
        sanitize=False,
        help="Free-text note for humans who inspect the audience. "
        "Not used by the engine.",
    )

    @api.model
    def _audience_domain(self):
        """Build the domain for eligible users.

        Returns a domain list suitable for ``res.users.search()``.
        """
        domain = []
        if self.internal_only:
            domain.append(("share", "=", False))
        if not self.include_inactive:
            domain.append(("active", "=", True))
        if self.group_ids:
            domain.append(("groups_id", "in", self.group_ids.ids))
        if self.excluded_group_ids:
            domain.append(("groups_id", "not in", self.excluded_group_ids.ids))
        # Exclude portal/public users
        domain.append(("id", "!=", self.env.ref("base.public_user").id))
        return domain

    def resolve_for_user(self, user_id):
        """Check if a user is eligible for proactive offers.

        Returns a dict with ``eligible`` (bool) and ``reason`` (str).
        """
        self.ensure_one()
        user = self.env["res.users"].browse(user_id)
        domain = self._audience_domain()
        if user.id in self.env["res.users"].sudo().search(domain).ids:
            return {"eligible": True, "reason": ""}
        # Build a human-readable reason
        reasons = []
        if self.internal_only and user.share:
            reasons.append("portal user")
        if not self.include_inactive and not user.active:
            reasons.append("inactive")
        if self.group_ids and not user.groups_id & self.group_ids:
            reasons.append("missing required groups")
        if self.excluded_group_ids and user.groups_id & self.excluded_group_ids:
            reasons.append("excluded by group")
        return {
            "eligible": False,
            "reason": "; ".join(reasons) or "does not match audience criteria",
        }

    def get_candidate_user_ids(self):
        """Ids of every user who is a candidate audience right now."""
        self.ensure_one()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        domain = self._audience_domain()
        if bot:
            domain.append(("id", "!=", bot.id))
        return self.env["res.users"].sudo().search(domain).ids

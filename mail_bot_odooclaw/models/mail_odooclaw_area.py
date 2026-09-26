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
a message nobody solicited is *impossible by construction*. Proactivity needs
the opposite flow, so it gets its own route and keeps the solicited one intact.
"""

import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# The metadata key the knowledge base and the playbooks share. Keeping one
# vocabulary on both sides is what lets "the trigger knows where the user is"
# meet "the knowledge base knows what to teach".
AREA_KEY = "area"


class MailOdooClawArea(models.Model):
    """Maps an Odoo view/action to a functional area and its signal counters.

    Rows are data: an administrator can retarget an area or change a threshold
    without touching code, which matters for material whose rules change (the
    VeriFactu deadlines already moved once with RDL 15/2025).
    """

    _name = "mail.odooclaw.area"
    _description = "OdooClaw Proactive Area"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    area = fields.Char(
        required=True,
        index=True,
        help="Functional area key shared with the knowledge base: "
        "contabilidad, ventas, compras, inventario, rrhh...",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(
        string="Proactive suggestions",
        default=True,
        help="When unchecked, entering this area never triggers a suggestion.",
    )
    model_name = fields.Char(
        help="Technical model that identifies this area, e.g. res.partner.",
    )
    view_ids = fields.Many2many(
        "ir.ui.view",
        string="Views",
        help="Views that belong to this area. Optional: the model is usually enough.",
    )
    action_ids = fields.Many2many(
        "ir.actions.act_window",
        string="Actions",
        help="Window actions that open this area.",
    )
    signal_definition = fields.Text(
        default="{}",
        help="JSON object mapping a signal key to the count expression used to "
        "build the counters, e.g. "
        '{"my_signal": {"model": "res.partner", "domain": [["active", "=", True]]}}.'
        " See the mail_bot_odooclaw_account module for real working examples.",
    )

    @api.constrains("area")
    def _check_area(self):
        for rec in self:
            if rec.area and rec.area != rec.area.strip().lower():
                raise models.ValidationError(
                    _("The area key must be lowercase and without spaces: %s", rec.area)
                )

    def _count_for(self, definition):
        """Count records for one signal definition. Returns 0 on any problem.

        Counting failures must never surface to the user: a bad definition
        should degrade to silence, not to an error dialog on a view open.
        """
        self.ensure_one()
        domain = definition.get("domain") or []
        model_name = definition.get("model") or self.model_name
        if not model_name:
            return 0

        # The module only depends on `mail`, so an area can legitimately point at
        # a model from a module that is not installed (Contabilidad needs
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
            counters[key] = self._count_for(definition)
        return counters

    @api.model
    def resolve_area(self, model_name, view_id=None, action_id=None):
        """Resolve the functional area for a screen, or an empty recordset.

        Resolution order, most specific first: window action, then view, then
        model. Deterministic on purpose — the same screen must always resolve to
        the same area, otherwise the cooldown behaves inconsistently.
        """
        base = self.search([("active", "=", True), ("enabled", "=", True)])
        if not base:
            return self.browse()

        if action_id:
            by_action = base.filtered(lambda r: action_id in r.action_ids.ids)
            if by_action:
                return by_action[0]

        if view_id:
            by_view = base.filtered(lambda r: view_id in r.view_ids.ids)
            if by_view:
                return by_view[0]

        if model_name:
            by_model = base.filtered(lambda r: r.model_name == model_name)
            if by_model:
                return by_model[0]

        return self.browse()


class OdooClawProactiveController:
    """Mixin-less controller holder; see ``controllers/main.py`` for the routes.

    The route itself is defined in main.py alongside the existing endpoints so
    all OdooClaw routes stay in one place; this class documents the contract and
    is intentionally not an http.Controller.
    """

    pass


def post_proactive_message(env, user_id, body, playbook_id, area):
    """Post an unsolicited offer to the bot's private chat with ``user_id``.

    Returns the created ``mail.message``. Raises ``ValueError`` with a
    human-readable reason on any refusal, which the caller turns into a 4xx.
    """
    # Everything below runs as superuser: an unsolicited post arrives on a public
    # route with no user session, so reading res.users or creating the private
    # channel would otherwise raise AccessError.
    env = env["res.users"].sudo().env

    bot_user = env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
    if not bot_user:
        raise ValueError("OdooClaw bot user not found")

    user = env["res.users"].browse(int(user_id))
    if not user.exists():
        raise ValueError("target user not found")

    partner = user.partner_id
    if not partner:
        raise ValueError("target user has no partner")

    # Reuse the exact private-channel resolution the solicited path uses, so
    # proactive and reply messages land in the same conversation.
    channel = env["mail.thread"].sudo()._resolve_private_reply_channel(
        partner, bot_user.partner_id
    )
    if not channel:
        raise ValueError("could not resolve the private channel")

    from ..utils.markdown_html import markdown_to_safe_html

    # Post as the bot so the message is attributed correctly and any reply the
    # user writes comes back through the normal webhook path.
    message = (
        channel.with_user(bot_user)
        .sudo()
        .message_post(
            body=markdown_to_safe_html(body),
            author_id=bot_user.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
    )
    message.sudo().write(
        {
            "odooclaw_proactive": True,
            "odooclaw_playbook_id": playbook_id or "",
            "odooclaw_area": area or "",
        }
    )

    # Mirror the "typing" cue the reply path shows, so a proactive message and a
    # reply feel like the same assistant.
    bot_member = channel.channel_member_ids.filtered(
        lambda m: m.partner_id.id == bot_user.partner_id.id
    )
    if bot_member:
        bot_member.sudo()._notify_typing(is_typing=False)

    _logger.info(
        "odooclaw: proactive message posted user_id=%s area=%s playbook=%s",
        user_id,
        area,
        playbook_id,
    )
    return message

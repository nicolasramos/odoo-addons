# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Provenance fields for proactive interventions.

These make a proactive message distinguishable from a reply in the chatter, in
the UI and in the database. Without them there is no way to measure the only
metric that decides whether this feature works — the acceptance rate of the
offer — and no way to audit why the assistant intervened.
"""

from odoo import fields, models


class MailMessage(models.Model):
    _inherit = "mail.message"

    odooclaw_proactive = fields.Boolean(
        string="Proactive suggestion",
        default=False,
        index=True,
        help="Set when this message was an unsolicited suggestion from "
        "OdooClaw, not a reply to a user message.",
    )
    odooclaw_playbook_id = fields.Char(
        string="OdooClaw playbook",
        help="Identifier of the playbook that produced this suggestion.",
    )
    odooclaw_area = fields.Char(
        string="OdooClaw area",
        help="Functional area the suggestion belongs to.",
    )

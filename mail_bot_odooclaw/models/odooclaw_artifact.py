# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Artifacts: what the assistant made, kept and findable.

A chat where the assistant builds something (a summary, a table, a snippet, a
small chart) loses it the moment the conversation scrolls. An artifact is that
thing stored on its own: named, typed, owned by the person who asked, linked to
the conversation it came from, and searchable later.

Storage is deliberately plain (HTML plus its plain-text twin) so an artifact
survives changes to whatever rendered it: it is a record in the database, not a
pointer to a screen.
"""

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

ARTIFACT_TYPES = [
    ("document", "Document"),
    ("table", "Table"),
    ("code", "Code"),
    ("chart", "Chart"),
    ("other", "Other"),
]


class OdooClawArtifact(models.Model):
    _name = "odooclaw.artifact"
    _description = "OdooClaw Artifact"
    _order = "create_date desc, id desc"

    name = fields.Char(
        required=True,
        help="What the artifact is, in the words of whoever asked for it.",
    )
    artifact_type = fields.Selection(
        ARTIFACT_TYPES,
        default="document",
        required=True,
        help="Kind of artifact. Used to group and filter; it does not change how "
        "the content is stored.",
    )
    content = fields.Html(
        sanitize=True,
        help="The artifact itself, as HTML. Sanitized on write: an artifact is "
        "data, never code that runs.",
    )
    plain_text = fields.Text(
        compute="_compute_plain_text",
        store=True,
        help="Searchable text version of the content, kept in sync automatically.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Owner",
        default=lambda self: self.env.user,
        required=True,
        index=True,
        help="Person the artifact belongs to. Only they and administrators see "
        "it.",
    )
    channel_id = fields.Many2one(
        "mail.channel",
        string="Conversation",
        ondelete="set null",
        help="Chat where the artifact was created, when it came from one.",
    )
    message_id = fields.Many2one(
        "mail.message",
        string="Message",
        ondelete="set null",
        help="Message the artifact replies to, when it came from one.",
    )
    tag_list = fields.Char(
        string="Tags",
        help="Comma-separated tags to find the artifact later: customer, "
        "invoice, q3...",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to archive the artifact without deleting it.",
    )

    @api.depends("content")
    def _compute_plain_text(self):
        for artifact in self:
            artifact.plain_text = html2plaintext(artifact.content or "")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("user_id"):
                vals["user_id"] = self.env.uid
        return super().create(vals_list)

    def name_get(self):
        result = []
        for artifact in self:
            result.append((artifact.id, artifact.name or _("Untitled artifact")))
        return result

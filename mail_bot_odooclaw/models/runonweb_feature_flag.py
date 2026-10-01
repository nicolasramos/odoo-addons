# © 2026 Nicolás Ramos — MIT License
"""
Feature flag model for per-field and per-user activation of runonweb features.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RunonwebFeatureFlag(models.Model):
    _name = "runonweb.feature.flag"
    _description = "runonweb feature flag"
    _order = "sequence, name"

    name = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10, help="Used to sort feature flags in the list view.")
    module_id = fields.Many2one(
        "ir.module.module",
        string="Module",
        domain="[('state', '=', 'installed')]",
        required=True,
        ondelete="cascade",
    )
    feature_type = fields.Selection(
        [("stt", "Speech-to-text"), ("ocr", "OCR"), ("embed", "Embeddings")],
        string="Feature type",
        required=True,
    )
    field_id = fields.Many2one(
        "ir.model.fields",
        string="Field",
        domain="[('ttype', 'in', ('text', 'html', 'char'))]",
        help="If set, this feature is enabled only for this field. "
             "Otherwise it applies to all text fields in the model.",
    )
    user_ids = fields.Many2many(
        "res.users",
        string="Allowed users",
        help="If set, only these users can use this feature. "
             "Empty means all users.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "feature_flag_uniq",
            "unique(module_id, feature_type, field_id)",
            "A feature flag must be unique per module, type, and field.",
        ),
    ]

    @api.constrains("field_id", "feature_type")
    def _check_field_compatibility(self):
        for rec in self:
            if rec.field_id and rec.feature_type not in ("stt", "ocr", "embed"):
                raise ValidationError(
                    _("Feature type '%s' cannot be restricted to a field.")
                    % rec.feature_type
                )

    def toggle_active(self):
        self.write({"active": not self.active})

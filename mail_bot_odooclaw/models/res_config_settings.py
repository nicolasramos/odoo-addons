# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw settings, all in one place.

What lives here is what an administrator must be able to change without a
developer: the global switch for processing incoming messages, and who
receives the work the bot cannot finish by default.

Every control in this block writes a parameter that the module actually reads.
That is the rule, not a preference: a control that writes a key nobody reads
promises the administrator an effect that does not exist, and a token stored
for a push nothing performs is a secret kept for nothing. The guard is a test
(``TestSettings.test_every_key_the_block_writes_has_a_reader``), so a key
cannot arrive here without a reader.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Areas whose model comes from an external module. Turning the pipeline on for
# one of them without the module installed would leave a dead configuration that
# looks alive, so the save is refused with the reason.
AREA_MODULES = {
    "helpdesk.ticket": "helpdesk_mgmt",
    "crm.lead": "crm",
}


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    odooclaw_pipeline_enabled = fields.Boolean(
        string="Process incoming messages",
        config_parameter="odooclaw.pipeline.enabled",
        help="Global switch for the operational pipeline. When a customer writes "
        "on a record of an area with a pipeline, the bot may observe, draft or "
        "answer according to that pipeline.",
    )
    odooclaw_pipeline_escalate_user_id = fields.Many2one(
        "res.users",
        string="Escalation user",
        config_parameter="odooclaw.pipeline.escalate_user_id",
        help="Default person who receives work the bot cannot finish: no answer, "
        "ambiguous request, or the customer asks for a human. A pipeline that "
        "names its own wins over this default.",
    )

    @api.constrains("odooclaw_pipeline_enabled")
    def _check_odooclaw_settings(self):
        for settings in self:
            if settings.odooclaw_pipeline_enabled:
                missing = self._missing_area_modules(settings)
                if missing:
                    raise ValidationError(
                        _(
                            "The pipeline is on for %(areas)s but %(modules)s "
                            "is not installed. Install it or disable those "
                            "areas first."
                        )
                        % {
                            "areas": ", ".join(sorted(missing)),
                            "modules": ", ".join(
                                sorted({AREA_MODULES[m] for m in missing})
                            ),
                        }
                    )

    @api.model
    def _missing_area_modules(self, settings=None):
        """Enabled pipeline areas whose external module is not installed."""
        pipeline_model = self.env["mail.odooclaw.pipeline"]
        if pipeline_model.search_count([]) == 0:
            return []
        pipelines = pipeline_model.search([("enabled", "=", True)])
        missing = set()
        for pipeline in pipelines:
            module_name = AREA_MODULES.get(pipeline.model_name)
            if not module_name:
                continue
            module = (
                self.env["ir.module.module"]
                .sudo()
                .search([("name", "=", module_name)], limit=1)
            )
            if not module or module.state != "installed":
                missing.add(pipeline.model_name)
        return missing

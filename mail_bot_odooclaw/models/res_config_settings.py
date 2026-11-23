# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""OdooClaw settings, all in one place.

What lives here is what an administrator must be able to change without a
developer: the global switch, the default mode, who receives escalations,
whether created fields must explain themselves, and the optional git repository
the bot pushes its generated modules to.

The repository is deliberately separate from the customer's Odoo project: it
holds what the bot builds, not the ERP source. If it is configured, generated
modules are pushed; if it is not, nothing leaves the instance.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .mail_odooclaw_pipeline import MODE_SELECTION

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
    odooclaw_pipeline_mode = fields.Selection(
        MODE_SELECTION,
        string="Default mode",
        config_parameter="odooclaw.pipeline.mode",
        default="draft",
        help="Mode a new pipeline starts with. Each pipeline can change it, and "
        "each stage can override it again.",
    )
    odooclaw_pipeline_escalate_user_id = fields.Many2one(
        "res.users",
        string="Escalation user",
        config_parameter="odooclaw.pipeline.escalate_user_id",
        help="Default person who receives work the bot cannot finish: no answer, "
        "ambiguous request, or the customer asks for a human.",
    )
    odooclaw_require_field_help = fields.Boolean(
        string="Require help on created fields",
        config_parameter="odooclaw.require_field_help",
        default=True,
        help="The change engine refuses to create a field without a help text. "
        "Turn it off only for a migration you control.",
    )
    odooclaw_repo_url = fields.Char(
        string="Bot repository URL",
        config_parameter="odooclaw.repo.url",
        help="Git repository the bot pushes its generated modules and change log "
        "to. This is the bot's own repository, never the customer's Odoo "
        "project. Leave empty to keep everything inside the instance.",
    )
    odooclaw_repo_branch = fields.Char(
        string="Bot repository branch",
        config_parameter="odooclaw.repo.branch",
        help="Branch the bot commits to, for example odooclaw/generated. Leave "
        "empty to use the repository default.",
    )
    odooclaw_repo_token = fields.Char(
        string="Bot repository token",
        config_parameter="odooclaw.repo.token",
        help="Token used to push. Stored as a system parameter, so it is only "
        "visible to administrators.",
    )
    odooclaw_repo_author = fields.Char(
        string="Bot repository author",
        config_parameter="odooclaw.repo.author",
        help="Name and email used for the bot's commits, e.g. "
        "'OdooClaw <bot@example.com>'.",
    )

    @api.constrains(
        "odooclaw_pipeline_enabled",
        "odooclaw_repo_url",
        "odooclaw_repo_token",
    )
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
            if settings.odooclaw_repo_url and not settings.odooclaw_repo_token:
                raise ValidationError(
                    _(
                        "A bot repository URL without a token cannot be pushed "
                        "to. Add the token or clear the URL."
                    )
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

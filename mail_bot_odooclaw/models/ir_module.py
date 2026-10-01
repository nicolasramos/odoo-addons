# Copyright 2026 INVITU (<https://www.invitu.com>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import threading
import requests
from odoo import models

_logger = logging.getLogger(__name__)


class Module(models.Model):
    _inherit = "ir.module.module"

    def button_immediate_install(self):
        result = super().button_immediate_install()
        self._notify_odooclaw_modules_md_rebuild()
        self._notify_odooclaw_reset_toolguard_cache()
        return result

    def button_immediate_uninstall(self):
        result = super().button_immediate_uninstall()
        self._notify_odooclaw_modules_md_rebuild()
        self._notify_odooclaw_reset_toolguard_cache()
        return result

    def _notify_odooclaw_modules_md_rebuild(self):
        """Notify OdooClaw to rebuild its MODULES.md memory file."""
        icp = self.env["ir.config_parameter"].sudo()
        webhook_url = icp.get_param(
            "odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo"
        )
        webhook_token = icp.get_param("odooclaw.webhook_token", "")

        installed = (
            self.sudo()
            .search([("state", "=", "installed")])
            .mapped("name")
        )
        payload = {"event": "modules_md_rebuild", "modules": installed}

        def send_webhook(url, data, token):
            try:
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["X-OdooClaw-Token"] = token
                response = requests.post(url, json=data, headers=headers, timeout=5)
                if response.status_code == 401:
                    _logger.error(
                        "OdooClaw rejected modules_md webhook: invalid token for %s", url
                    )
            except Exception as e:
                _logger.error("OdooClaw: failed to send webhook: %s", e)

        system_url = webhook_url.rstrip("/") + "/system"
        threading.Thread(
            target=send_webhook, args=(system_url, payload, webhook_token)
        ).start()

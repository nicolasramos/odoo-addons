# Copyright 2026 INVITU (<https://www.invitu.com>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging
import threading

import requests

from odoo import models

_logger = logging.getLogger(__name__)


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    def write(self, vals):
        res = super().write(vals)
        if "odooclaw.denied_models" in self.mapped("key"):
            self._notify_odooclaw_reset_toolguard_cache()
        return res

    def _notify_odooclaw_reset_toolguard_cache(self):
        """Notify OdooClaw that the denied models list has changed."""
        icp = self.env["ir.config_parameter"].sudo()
        webhook_url = icp.get_param(
            "odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo"
        )
        webhook_token = icp.get_param("odooclaw.webhook_token", "")
        payload = {"event": "config_changed", "keys": ["odooclaw.denied_models"]}

        def send_webhook(url, data, token):
            try:
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["X-OdooClaw-Token"] = token
                response = requests.post(url, json=data, headers=headers, timeout=5)
                if response.status_code == 401:
                    _logger.error(
                        "OdooClaw rejected denied_models webhook: invalid token for %s", url
                    )
            except Exception as e:
                _logger.error(
                    "Failed to send denied_models webhook to OdooClaw: %s", str(e)
                )

        system_url = webhook_url.rstrip("/") + "/system"
        threading.Thread(
            target=send_webhook, args=(system_url, payload, webhook_token)
        ).start()

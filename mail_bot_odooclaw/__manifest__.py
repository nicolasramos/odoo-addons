# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "OdooClaw AI Bot",
    "version": "18.0.1.2.0",
    "category": "Discuss",
    "summary": "Integrate OdooClaw AI agent via webhooks in Odoo Discuss",
    "author": "Nicolás Ramos",
    "license": "AGPL-3",
    "depends": ["mail"],
    "data": [
        "security/odooclaw_security.xml",
        "security/ir.model.access.csv",
        "data/odooclaw_bot_data.xml",
        "data/odooclaw_audience_data.xml",
        "data/odooclaw_cron.xml",
        "views/mail_odooclaw_audience_views.xml",
        "views/proactive_assets.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "maintainer": "nicolasramos",
    "development_status": "Beta",
}

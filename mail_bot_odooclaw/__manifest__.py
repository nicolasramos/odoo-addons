{
    "name": "OdooClaw AI Bot",
    "version": "18.0.1.1.0",
    "category": "Discuss",
    "summary": "Integrate OdooClaw AI agent via webhooks in Odoo Discuss",
    "author": "Nicolás Ramos",
    "license": "AGPL-3",
    "depends": ["mail"],
    "data": [
        "security/odooclaw_security.xml",
        "security/ir.model.access.csv",
        "data/odooclaw_bot_data.xml",
        "data/odooclaw_cron.xml",
        "data/runonweb_feature_flags_data.xml",
        "views/runonweb_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mail_bot_odooclaw/static/src/js/runonweb_bundle.js",
            "mail_bot_odooclaw/static/src/js/runonweb_bridge.js",
            "mail_bot_odooclaw/static/src/js/embed_semantic_search.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "maintainer": "nicolasramos",
    "development_status": "Beta",
}

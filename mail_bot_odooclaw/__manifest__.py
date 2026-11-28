{
    "name": "OdooClaw AI Bot",
    "version": "16.0.1.9.0",
    "category": "Discuss",
    "summary": "Integrate OdooClaw AI agent via webhooks in Odoo Discuss",
    "description": """Connects Odoo Discuss to an OdooClaw engine through
webhooks. An @mention in a channel or a record chatter creates a pipeline
run, the engine answers through a reply token, and the areas modules add
proactive assistance per model and stage. See the module README for the
webhook contract.""",
    "author": "Nicolás Ramos",
    "license": "AGPL-3",
    "depends": ["mail", "base_setup", "odooclaw_mcp"],
    "data": [
        "security/odooclaw_security.xml",
        "security/ir.model.access.csv",
        "data/odooclaw_bot_data.xml",
        "data/odooclaw_audience_data.xml",
        "data/odooclaw_cron.xml",
        "views/mail_odooclaw_audience_views.xml",
        "views/mail_odooclaw_pipeline_views.xml",
        "views/odooclaw_artifact_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "maintainer": "nicolasramos",
    "development_status": "Beta",
}

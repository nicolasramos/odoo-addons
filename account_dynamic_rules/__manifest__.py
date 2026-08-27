# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Account Dynamic Rules",
    "summary": "Dynamic rules for account, product and payment terms mapping",
    "version": "19.0.1.0.3",
    "category": "Accounting",
    "author": "Nicolás Ramos",
    "maintainers": ["nicolasramos"],
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "account",
        "account_fiscal_position",
    ],
    "external_dependencies": {
        "python": [],
    },
    "data": [
        "security/ir.model.access.csv",
        "security/account_dynamic_rules_security.xml",
        "views/account_dynamic_rule_view.xml",
    ],
}

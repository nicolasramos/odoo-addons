# Odoo Addons

Public Odoo addon repository.

This repository contains installable Odoo addons intended to be consumed through a standard Odoo addons path, Git aggregator, submodule, deployment template, or any other Odoo-compatible source management flow.

This is the **17.0** branch. The `mail_bot_odooclaw` family and `odooclaw_mcp` are ported from the 18.0 line; `odoo_agent` is not available on this branch.

## Available addons

| Addon | Odoo versions | Summary | Documentation |
| --- | --- | --- | --- |
| `mail_bot_odooclaw` | 17.0 | OdooClaw AI bot integration with Odoo Discuss via webhooks. Requires `odooclaw_mcp`. | [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md) |
| `odooclaw_mcp` | 17.0 | MCP endpoint served by Odoo, whose tools are declared as server actions. | [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md) |
| `mail_bot_odooclaw_account` | 17.0 | Proactive assistance: Accounting areas. Requires `mail_bot_odooclaw`. | [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md#proactive-assistance--one-module-per-area) |
| `mail_bot_odooclaw_sale` | 17.0 | Proactive assistance: Sales areas. | ↑ |
| `mail_bot_odooclaw_crm` | 17.0 | Proactive assistance: CRM areas. | ↑ |
| `mail_bot_odooclaw_helpdesk` | 17.0 | Proactive assistance: Helpdesk areas. Requires `helpdesk_mgmt`. | ↑ |
| `mail_bot_odooclaw_purchase` | 17.0 | Proactive assistance: Purchase areas. | ↑ |
| `mail_bot_odooclaw_stock` | 17.0 | Proactive assistance: Inventory areas. | ↑ |
| `mail_bot_odooclaw_hr` | 17.0 | Proactive assistance: Human resources areas. | ↑ |
| `mail_bot_odooclaw_expense` | 17.0 | Proactive assistance: Expenses areas. | ↑ |
| `mail_bot_odooclaw_project` | 17.0 | Proactive assistance: Projects areas. | ↑ |
| `mail_bot_odooclaw_fleet` | 17.0 | Proactive assistance: Fleet areas. | ↑ |
| `mail_bot_odooclaw_knowledge` | 17.0 | OdooClaw answers from the `document_page` knowledge base, citing the page it used. Requires `mail_bot_odooclaw` and `document_page`. | [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md#knowledge-answers-from-the-document-pages) |
| `account_dynamic_rules` | 17.0 | Dynamic rules for account, product and payment terms mapping. | [`account_dynamic_rules/readme/DESCRIPTION.rst`](account_dynamic_rules/readme/DESCRIPTION.rst) |

## Repository strategy

This repository contains Odoo addons only.

Runtime daemons, OS installers, service files, and machine-side execution code live in a separate repository:

- Runtime: `https://github.com/nicolasramos/odoo-agent-runtime`

This separation keeps each project clean:

| Repository | Owns | Release rhythm |
| --- | --- | --- |
| `odoo-addons` | Odoo modules, manifests, XML views, models, security, Odoo tests, addon docs. | Odoo-versioned releases, for example `16.0.1.9.0`. |
| `odoo-agent-runtime` | Cross-platform daemon, installers, OS service integration, runtime docs, smoke tests. | Runtime semver releases, for example `0.1.0`. |

## Branches

Each Odoo major version has its own branch:

| Branch | Contains |
| --- | --- |
| `16.0` | `mail_bot_odooclaw` family, `odooclaw_mcp`, `account_dynamic_rules` |
| `17.0` | `mail_bot_odooclaw` family |
| `18.0` | `odoo_agent`, `mail_bot_odooclaw` family, `odooclaw_mcp` |
| `19.0` | `odoo_agent`, `mail_bot_odooclaw` family |

The default branch (`main`) tracks the latest Odoo version (18.0).

## Installation pattern

Add this repository to your Odoo addons path and install the desired module.

Example:

```ini
[options]
addons_path = /opt/odoo/odoo/addons,/opt/odoo/odoo-addons
```

Then install one or more modules:

```bash
odoo-bin -d <database> -i mail_bot_odooclaw --stop-after-init
```

The helpdesk and knowledge area modules need the OCA addons on the addons path:

- `helpdesk_mgmt` from `https://github.com/OCA/helpdesk` (branch 16.0)
- `document_page` from `https://github.com/OCA/knowledge` (branch 16.0)

## Documentation

- [`docs/repository-structure.md`](docs/repository-structure.md) — how this repository is organized.
- [`docs/release-policy.md`](docs/release-policy.md) — release and compatibility policy.
- [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md) — mail_bot_odooclaw addon documentation.

## Validate

```bash
# Static validation for all addons
python3 .github/scripts/validate_addon.py
python3 -m compileall -q mail_bot_odooclaw odooclaw_mcp
```

Full validation requires Odoo:

```bash
odoo-bin -d <database> -i odooclaw_mcp,mail_bot_odooclaw --test-enable --stop-after-init
```

## Author

Maintained by **Nicolás Ramos** ([nicolasramos.es](https://nicolasramos.es), [@nicolasramos_es](https://twitter.com/nicolasramos_es)).

## License

This repository contains modules under different licenses. Check each addon's `__manifest__.py` for the applicable license.

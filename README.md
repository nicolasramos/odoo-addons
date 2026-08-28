# Odoo Addons

Public Odoo addon repository.

This repository contains installable Odoo addons intended to be consumed through a standard Odoo addons path, Git aggregator, submodule, deployment template, or any other Odoo-compatible source management flow.

## Available addons

| Addon | Odoo versions | Summary | Documentation |
| --- | --- | --- | --- |
| `odoo_agent` | 18.0 | AI agent execution system for Odoo Project: runtimes, agents, executions, logs, skills, MCP, and `@mentions`. | [`odoo_agent/README.md`](odoo_agent/README.md) |
| `mail_bot_odooclaw` | 16.0, 17.0, 18.0, 19.0 | OdooClaw AI bot integration with Odoo Discuss via webhooks. | [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md) |

## Repository strategy

This repository contains Odoo addons only.

Runtime daemons, OS installers, service files, and machine-side execution code live in a separate repository:

- Runtime: `https://github.com/nicolasramos/odoo-agent-runtime`

This separation keeps each project clean:

| Repository | Owns | Release rhythm |
| --- | --- | --- |
| `odoo-addons` | Odoo modules, manifests, XML views, models, security, Odoo tests, addon docs. | Odoo-versioned releases, for example `18.0.1.4.0`. |
| `odoo-agent-runtime` | Cross-platform daemon, installers, OS service integration, runtime docs, smoke tests. | Runtime semver releases, for example `0.1.0`. |

## Branches

Each Odoo major version has its own branch:

| Branch | Contains |
| --- | --- |
| `16.0` | `mail_bot_odooclaw` |
| `17.0` | `mail_bot_odooclaw` |
| `18.0` | `odoo_agent`, `mail_bot_odooclaw` |
| `19.0` | `odoo_agent`, `mail_bot_odooclaw` |

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
odoo-bin -d <database> -i odoo_agent --stop-after-init
odoo-bin -d <database> -i mail_bot_odooclaw --stop-after-init
```

## Documentation

- [`docs/repository-structure.md`](docs/repository-structure.md) — how this repository is organized.
- [`docs/release-policy.md`](docs/release-policy.md) — release and compatibility policy.
- [`odoo_agent/README.md`](odoo_agent/README.md) — odoo_agent addon documentation.
- [`odoo_agent/docs/installation.md`](odoo_agent/docs/installation.md) — install the odoo_agent addon.
- [`odoo_agent/docs/runtime-installation.md`](odoo_agent/docs/runtime-installation.md) — connect the external runtime for odoo_agent.
- [`mail_bot_odooclaw/README.md`](mail_bot_odooclaw/README.md) — mail_bot_odooclaw addon documentation.

## Validate

```bash
# Static validation for all addons
python3 .github/scripts/validate_addon.py
python3 -m compileall -q odoo_agent mail_bot_odooclaw
```

Full validation requires Odoo:

```bash
odoo-bin -d <database> -i odoo_agent,mail_bot_odooclaw --test-enable --stop-after-init
```

## Author

Maintained by **Nicolás Ramos** ([nicolasramos.es](https://nicolasramos.es), [@nicolasramos_es](https://twitter.com/nicolasramos_es)).

## License

This repository contains modules under different licenses. Check each addon's `__manifest__.py` for the applicable license.

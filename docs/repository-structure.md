# Repository structure

This repository is an Odoo addons repository. It should stay focused on installable Odoo modules and their supporting documentation, tests, and quality tooling.

## Layout

```text
odoo-addons/
├── README.md
├── LICENSE
├── docs/
│   ├── repository-structure.md
│   └── release-policy.md
├── .github/
│   └── scripts/
│       └── validate_addon.py
└── odoo_agent/
    ├── __manifest__.py
    ├── models/
    ├── controllers/
    ├── views/
    ├── security/
    ├── tests/
    └── docs/
```

## What belongs here

- Odoo addon source code.
- Odoo manifests and data files.
- Odoo XML views and actions.
- Odoo security files.
- Addon tests.
- Addon documentation.
- Repository-level validation scripts.

## What does not belong here

- Runtime daemon source code.
- OS service installers.
- `.env` files.
- Machine-specific logs.
- CLI binaries.
- Deployment secrets.

Those belong in the runtime repository or in private deployment infrastructure.

## Addon consumption

This repository is designed to work with standard Odoo deployment patterns:

- direct `addons_path` checkout;
- Git aggregator;
- Git submodule;
- deployment-template sync;
- container image build step.

Each addon should remain installable independently from the repository root.

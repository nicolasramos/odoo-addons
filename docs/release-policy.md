# Release policy

The Odoo addon repository and the runtime repository have separate release rhythms.

## Odoo addons

Odoo addons use Odoo-style versions in each `__manifest__.py`:

```text
18.0.<major>.<minor>.<patch>
```

Use this when the change depends on Odoo 18 APIs, Odoo data migrations, XML views, model fields, security, or addon behavior.

## Runtime

The runtime uses semantic versioning:

```text
<major>.<minor>.<patch>
```

Use this when the change affects daemon behavior, installers, service integration, CLI execution, or runtime protocol handling.

## Compatibility policy

Document compatibility in both repositories.

Example:

| Addon version | Runtime version | Notes |
| --- | --- | --- |
| `18.0.1.4.x` | `>=0.1.0 <0.2.0` | First public execution API. |

## Release checklist

Before publishing an addon release:

- [ ] Static validation passes.
- [ ] Odoo 18 install/upgrade passes.
- [ ] Odoo tests pass.
- [ ] Runtime compatibility is documented.
- [ ] README and docs are updated.

Before publishing a runtime release:

- [ ] Smoke tests pass.
- [ ] Linux manual run is validated.
- [ ] macOS manual run is validated.
- [ ] Windows manual run is validated.
- [ ] Service/daemon installation docs are current.
- [ ] Addon compatibility is documented.

# Odoo AI Agent System

Odoo AI Agent System turns Odoo 18 Project into an operational control layer for AI agents. Teams can assign a Project task to an agent, execute it on an external runtime, stream logs, retry or cancel work, and keep the final result attached to the task history.

This is not a chat widget. It is an auditable execution system for agent teams inside Odoo.

## What you get

- Assign agents directly from Odoo Project tasks.
- Run work on external Linux, macOS, or Windows machines.
- Track execution states: `queued`, `running`, `waiting_input`, `completed`, `failed`, and `cancelled`.
- Stream logs and final results back into Odoo.
- Configure engines, CLI commands, instructions, skills, MCP servers, timeouts, retries, and concurrency.
- Delegate work to other agents from prompts with `@mentions`.
- Keep access controlled with Odoo groups, companies, Project visibility, and runtime-scoped API keys.

## Quick path

1. Install this addon on Odoo 18.
2. Assign users to **Agent User** or **Agent Admin**.
3. Create a runtime in **AI Agents → Runtimes** and generate an API key.
4. Install the runtime daemon on the machine that will execute agent CLIs.
5. Create an agent with runtime, engine, CLI command, instructions, skills, and limits.
6. Assign that agent to a Project task and click **Send to Agent**.
7. Watch status, logs, result, retries, cancellation, and chatter updates in Odoo.

## Architecture

```text
Odoo 18
├── project.task              → Native task workflow: assign, send, retry, cancel, inspect
├── odoo.agent                → Agent configuration and operational limits
├── odoo.agent.execution      → One auditable run for a task
├── odoo.agent.log            → Runtime logs for each execution
├── odoo.agent.runtime        → External runtime identity and API key
├── odoo.agent.skill          → Reusable instruction packs
└── odoo.agent.mcp.server     → MCP tool/data-source configuration

External runtime
└── polls Odoo → receives execution → runs CLI → streams logs → completes/fails
```

## Supported engines

The addon supports engine presets and custom commands. Production behavior is driven by the agent's `cli_command`, so any CLI-based agent can be connected when the runtime host can execute it.

| Engine | Typical use |
| --- | --- |
| Codex | Code and repository work through a Codex-compatible CLI. |
| Hermes | Hermes gateway/runtime setups. |
| OpenCode | OpenCode CLI execution. |
| OpenClaw | OpenClaw agent execution. |
| Claude Code | Claude Code CLI execution. |
| Custom CLI | Any local agent command available on the runtime host. |

Example commands:

```text
opencode run {instruction}
hermes run --context {instruction}
openclaw agent --task {task_name} --context {instruction}
claude --print {instruction}
```

## Runtime daemon

The external runtime daemon lives in a separate repository/package. It is responsible for:

- reading Odoo URL and runtime API key;
- registering heartbeat and capabilities;
- polling queued executions;
- building the final instruction from Odoo configuration;
- executing the configured local CLI;
- streaming logs;
- reporting completion, failure, or cancellation.

See:

- [`docs/runtime-installation.md`](docs/runtime-installation.md)
- [`docs/runtime-contract.md`](docs/runtime-contract.md)

## Orchestration in Odoo

[`docs/agent-orchestration.md`](docs/agent-orchestration.md) closes the loop
without any extra module: assign an agent, dispatch automatically on assignment
or on stage entry, map execution states to project stages per project, and
mention agents in the chatter of any record.

`odoo_agent_sale` extends the same loop to quotations and sales orders, so a
salesperson can write `@hermes review this quotation` in the order chatter and
get the answer in the same thread.

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/installation.md`](docs/installation.md) | Install and configure the Odoo addon. |
| [`docs/runtime-installation.md`](docs/runtime-installation.md) | Install the runtime on Linux, macOS, and Windows. |
| [`docs/user-guide.md`](docs/user-guide.md) | Daily workflow for Project users and operators. |
| [`docs/configuration.md`](docs/configuration.md) | Agents, skills, MCP servers, timeouts, retries, and engines. |
| [`docs/runtime-contract.md`](docs/runtime-contract.md) | Runtime API endpoints and payloads. |
| [`docs/compatibility.md`](docs/compatibility.md) | Addon/runtime version compatibility. |
| [`docs/agent-mentions.md`](docs/agent-mentions.md) | Multi-agent delegation with `@mentions`. |
| [`docs/security.md`](docs/security.md) | Groups, record rules, API keys, companies, and safe operation. |
| [`docs/translations.md`](docs/translations.md) | Translation coverage and regeneration workflow. |
| [`docs/development.md`](docs/development.md) | Development, tests, validation, and contribution workflow. |
| [`docs/release-checklist.md`](docs/release-checklist.md) | Public release checklist. |
| [`docs/demo-script.md`](docs/demo-script.md) | Demo data, screenshots, and video script. |

## Screenshots

<div align="center">
  <img src="static/description/screenshots/Captura%20de%20pantalla%202026-07-12%20a%20las%2019.01.03.png" alt="Task with agent communication" width="700">
  <p><em>Task with agent communications, execution logs and agent chat</em></p>
</div>

<div align="center">
  <img src="static/description/screenshots/Captura%20de%20pantalla%202026-07-12%20a%20las%2019.03.17.png" alt="Agent execution list" width="700">
  <p><em>Execution history with status, timestamps and log counts per run</em></p>
</div>

<div align="center">
  <img src="static/description/screenshots/Captura%20de%20pantalla%202026-07-12%20a%20las%2019.04.02.png" alt="Runtime configuration" width="700">
  <p><em>Runtime detail with health status, version info, IP and heartbeat history</em></p>
</div>

<div align="center">
  <img src="static/description/screenshots/Captura%20de%20pantalla%202026-07-12%20a%20las%2019.05.09.png" alt="Agent configuration form" width="700">
  <p><em>Agent setup: runtime, engine, CLI command, model, limits and instructions</em></p>
</div>

<div align="center">
  <img src="static/description/screenshots/Captura%20de%20pantalla%202026-07-12%20a%20las%2019.08.40.png" alt="Agent chatter and status log" width="700">
  <p><em>Agent activity log: state changes, engine switches, working/idle/error cycles</em></p>
</div>


## Installation summary

```bash
# Add this repository to your Odoo addons path, then update apps.
odoo-bin -d <database> -i odoo_agent --stop-after-init
```

Then install the runtime and connect it with the generated API key.

## Security model

| Group | Purpose |
| --- | --- |
| Agent User | Operate agent executions and read operational records. |
| Agent Admin | Manage runtimes, API keys, agents, skills, MCP servers, and mappings. |

Runtime API keys are scoped to one runtime. A runtime can only operate on executions assigned to that runtime.

## Validation

Static validation without a database:

```bash
python3 scripts/validate_addon.py
python3 -m compileall -q odoo_agent
```

Full validation with Odoo:

```bash
odoo-bin -d <database> -i odoo_agent --test-enable --stop-after-init
```


## Author

**odoo_agent** was created and is maintained by **Nicolás Ramos**
([nicolasramos.es](https://nicolasramos.es)).

## Public readiness status

The module is structured for a public release, but before publishing a production tag you should validate it on a real Odoo 18 database with the runtime daemon connected end-to-end.

See [`docs/release-checklist.md`](docs/release-checklist.md).

## License

LGPL-3.

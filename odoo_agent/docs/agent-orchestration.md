# Assigning work to an AI agent

This guide covers the full loop inside Odoo: assign a record to an agent, run it
on an external runtime, follow the execution and let Odoo move the stage when the
run finishes.

## 1. The two layers

| Layer | Responsibility | Transport |
| --- | --- | --- |
| `odoo_agent` | Queue, audit trail, logs, status and stage mapping | Pull: the runtime polls Odoo |
| External runtime (`odoo-agent-runtime`) | Executes the agent CLI on a real machine | HTTP with the runtime API key |

The module does not need the community `ai_oca_bridge` to work. The bridge is a
useful extra when you want Odoo to notify an HTTP endpoint, but it is not part of
the execution contract.

## 2. Assign and run

1. Create an `odoo.agent` with a runtime, engine and CLI command.
2. Assign the agent to a task (`AI Agent` field) or to a quotation if
   `odoo_agent_sale` is installed.
3. With **Dispatch On Assignment** enabled, the execution is queued immediately.
   Disable it for agents that must only run from the button.
4. The runtime polls `GET /api/agent/runtime/poll`, executes the CLI and reports
   `start`, `log`, `complete` or `fail`.

Two automatic triggers exist:

- **On assignment**: writing `agent_id` on a record queues one execution.
- **On stage entry**: mark a project stage with *Dispatch AI Agent On Entry*
  (`AI Agents > Configuration > Dispatch Stages`). Every task entering that stage
  with an agent assigned queues a run.

Both triggers skip the queue when the same record already has an active
execution for that agent, so a double click cannot duplicate work.

## 3. Stage mapping

`AI Agents > Configuration > Stage Mapping` maps an execution status to a project
stage. The mapping is resolved per project first and falls back to the company
wide entry, so several projects with different stage names can coexist.

Recommended setup:

| Execution status | Stage |
| --- | --- |
| `queued` | Ready |
| `running` | In progress |
| `completed` | Review |
| `failed` | Blocked |

The agent never writes the stage itself. Odoo applies the mapping when the
execution changes status, which keeps the board deterministic. A stage change
performed by the mapping does not re-trigger automatic dispatch.

## 4. What the runtime receives

`to_runtime_payload()` returns the execution plus a `record` block with the
target data: name, description, stage, project, tags, assignees, attachments and
a backend URL. `odoo_agent_sale` adds partner, amounts and order lines.

Additional endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/agent/execution/{id}/context` | Refresh the record payload during a long run |
| `GET /api/agent/execution/{id}/attachment/{attachment_id}` | Download an attachment of the record |
| `POST /api/agent/execution/{id}/message` | Post a progress message in the record chatter |

## 5. Mentions in the chatter

Any model using `odoo.agent.mixin` understands `@handle` in the chatter:

```text
@hermes review this quotation and list the missing data
```

Odoo resolves the handle against `odoo.agent.mention_key`, queues an execution
with `source=mention` and posts the answer back in the same thread. Portal users
cannot trigger agents, and messages posted by the agent itself never start a new
run.

`project.task` and `sale.order` ship with the mixin. To add another model:

```python
class HelpdeskTicket(models.Model):
    _name = 'helpdesk.ticket'
    _inherit = ['helpdesk.ticket', 'odoo.agent.mixin']

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        self._agent_hook_message_post(message)
        return message
```

## 6. Watchdog and retries

- A cron marks `running` executions as failed when no heartbeat arrives for
  longer than `timeout_seconds + 600`.
- If the execution has `retry_limit > 0`, a failed run creates a child attempt
  automatically until the limit is reached.
- `complete` and `fail` are idempotent: a repeated callback from the runtime does
  not duplicate chatter messages.

## 7. The bridge module: when it helps and when it hurts

`ai_oca_bridge` (AGPL-3) posts a JSON payload to an external URL when a record or
a Discuss channel changes. It is a notifier, not an execution queue:

- `ai_oca_bridge_chatter` only triggers on `discuss.channel` messages. It does
  not hook the chatter of a task, a quotation or a ticket.
- Immediate calls have a fixed 30 second timeout, too short for development work.
- AGPL-3 spreads to any product you distribute. Keep it in your own installation
  or replace it with a small webhook of your own.

Use it for a chat assistant in Discuss. Use `odoo_agent` for auditable work on
records.

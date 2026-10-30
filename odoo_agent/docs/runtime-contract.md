# Runtime Contract

The Odoo addon and the external runtime communicate through a small JSON HTTP contract. The runtime is a separate process and should be treated as an untrusted integration client scoped by API key.

## Authentication

The runtime sends its API key through `X-API-Key` or `api_key`.

Odoo resolves the key to exactly one `odoo.agent.runtime`. Every execution/log operation must belong to that runtime.

## Poll response

`GET /api/agent/runtime/poll` returns queued executions:

```json
{
  "status": "ok",
  "executions": [
    {
      "id": 123,
      "name": "Task name",
      "prompt": "Full execution prompt",
      "timeout_seconds": 3600,
      "agent": {
        "engine": "opencode",
        "cli_command": "opencode run {instruction}",
        "instructions": "Agent rules",
        "skills": [],
        "mcp_servers": []
      }
    }
  ]
}
```

Legacy `tasks` remains only as compatibility fallback.

## Lifecycle endpoints

| Action | Endpoint |
| --- | --- |
| Start | `POST /api/agent/execution/{id}/start` |
| Log | `POST /api/agent/execution/{id}/log` |
| Progress message | `POST /api/agent/execution/{id}/message` |
| Context | `GET /api/agent/execution/{id}/context` |
| Attachment | `GET /api/agent/execution/{id}/attachment/{attachment_id}` |
| Complete | `POST /api/agent/execution/{id}/complete` |
| Fail | `POST /api/agent/execution/{id}/fail` |
| Request cancel | `POST /api/agent/execution/{id}/cancel` |
| Acknowledge cancel | `POST /api/agent/execution/{id}/cancel/ack` |
| Read logs | `GET /api/agent/execution/{id}/logs` |

## Record context

Every execution payload includes a `record` block with the target record data.
Project tasks expose name, description, project, stage, tags, assignees and
attachments. Models that use `odoo.agent.mixin` can add their own fields by
overriding `_agent_context_payload()`.

```json
{
  "res_model": "project.task",
  "res_id": 42,
  "record": {
    "name": "Fix the invoice export",
    "description": "The CSV export misses the tax column.",
    "project": "Billing",
    "stage": "In progress",
    "tags": ["bug"],
    "attachments": [{"id": 7, "name": "trace.txt", "mimetype": "text/plain"}],
    "url": "https://odoo.example.com/web#id=42&model=project.task&view_type=form"
  }
}
```

## Runtime behavior expectations

- Use `prompt` as the primary execution input.
- Use `agent.cli_command` when present.
- Preserve long prompts as one CLI argument or pass them via an explicit file placeholder.
- If the configured CLI is missing, fail the execution.
- Never report fake success when the CLI was not executed.
- Stream useful logs back to Odoo while running.


## Chat execution contract

Chat messages are executed through the same `odoo.agent.execution` lifecycle used by Project tasks.

The main Odoo UI creates these messages from the Project task **Agent Communications** tab. External clients can use `POST /api/agent/{agent_id}/chat`.

When a user sends a chat message, Odoo creates:

- one `odoo.agent.chat.message` with `author_type=user`;
- one queued `odoo.agent.execution` with `source=chat`;
- a link from the message to the execution.

Runtime polling then returns the execution with additional chat context:

```json
{
  "source": "chat",
  "chat_message_id": 10,
  "conversation": [
    {"author_type": "user", "content": "Can you review this?"}
  ]
}
```

When the runtime completes the execution, Odoo creates an agent chat reply from the execution result.

For `source=chat`, runtimes should treat `prompt` as the current user message. They should not prepend the execution `name` or Project task title as the primary task instruction, otherwise short messages like "hello" can be incorrectly interpreted as requests to work on the task title.

The runtime can also send intermediate chat replies with:

```http
POST /api/agent/execution/{id}/message
```

Payload:

```json
{
  "message": "I am checking the logs now."
}
```

## Realtime notifications

The addon publishes Odoo bus notifications with notification type `odoo_agent`.

Events:

| Event | Meaning |
| --- | --- |
| `chat_message_created` | A chat message was created. |
| `chat_message_updated` | A chat message state changed. |
| `execution_updated` | Execution status/result/error changed. |
| `log_created` | Runtime created an execution log. |

Channels use these names:

```text
odoo_agent.agent.{agent_id}
odoo_agent.execution.{execution_id}
odoo_agent.project_task.{project_task_id}
```

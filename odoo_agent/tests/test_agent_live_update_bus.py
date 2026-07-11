# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAgentLiveUpdateBus(TransactionCase):
    """Tests for the bus.bus notifications that back the live-update JS client.

    The JavaScript client ``agent_live_update`` subscribes to three channel
    families:

      - ``odoo_agent.execution.{id}``
      - ``odoo_agent.agent.{id}``
      - ``odoo_agent.project_task.{id}``

    Every notification it forwards to the page uses ``type="odoo_agent"``
    and a payload that includes an ``event`` field. This test makes sure
    the backend honours that contract so the JS patch can rely on it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runtime = cls.env["odoo.agent.runtime"].create(
            {
                "name": "Live Update Runtime",
                "machine_id": "live-update-runtime",
                "company_id": cls.env.company.id,
            }
        )
        cls.runtime.action_generate_api_key()
        cls.skill = cls.env["odoo.agent.skill"].create(
            {
                "name": "Live Update Skill",
                "instructions": "Be terse.",
                "category": "analysis",
                "company_id": cls.env.company.id,
            }
        )
        cls.mcp_server = cls.env["odoo.agent.mcp.server"].create(
            {
                "name": "Live Update MCP",
                "server_key": "live-update-mcp",
                "transport": "stdio",
                "command": "python",
                "args": "-m test_server",
                "company_id": cls.env.company.id,
            }
        )
        cls.agent = cls.env["odoo.agent"].create(
            {
                "name": "Live Update Agent",
                "runtime_id": cls.runtime.id,
                "engine": "hermes",
                "cli_command": "hermes run --context {instruction}",
                "instructions": "Work the assigned task.",
                "skill_ids": [(6, 0, cls.skill.ids)],
                "mcp_server_ids": [(6, 0, cls.mcp_server.ids)],
                "company_id": cls.env.company.id,
            }
        )
        cls.project = cls.env["project.project"].create(
            {"name": "Live Update Project", "company_id": cls.env.company.id}
        )
        cls.task = cls.env["project.task"].create(
            {
                "name": "Live Update Task",
                "description": "Trigger live updates.",
                "project_id": cls.project.id,
                "company_id": cls.env.company.id,
                "agent_id": cls.agent.id,
            }
        )

    def _capture_sendone(self):
        bus = self.env["bus.bus"]
        calls = []
        original = type(bus)._sendone

        def patched(record, target, notification_type, message):
            calls.append(
                {
                    "target": target,
                    "type": notification_type,
                    "payload": dict(message) if message else {},
                }
            )
            return original(record, target, notification_type, message)

        type(bus)._sendone = patched
        return calls, original

    def test_execution_action_start_publishes_to_three_channels(self):
        execution = self.env["odoo.agent.execution"].create(
            {
                "name": "Live Update Exec",
                "prompt": "Run me.",
                "agent_id": self.agent.id,
                "task_id": self.task.id,
                "company_id": self.env.company.id,
            }
        )
        calls, original = self._capture_sendone()
        try:
            execution.action_start()
        finally:
            type(self.env["bus.bus"]).__class__._sendone = original

        targets = {c["target"] for c in calls if c["type"] == "odoo_agent"}
        self.assertIn(f"odoo_agent.execution.{execution.id}", targets)
        self.assertIn(f"odoo_agent.agent.{self.agent.id}", targets)
        self.assertIn(f"odoo_agent.project_task.{self.task.id}", targets)

        # The execution_updated payload must carry the id and status so the
        # JS form patch can match it without a server round trip.
        exec_payloads = [
            c["payload"]
            for c in calls
            if c["type"] == "odoo_agent" and c["payload"].get("event") == "execution_updated"
        ]
        self.assertTrue(exec_payloads, "Expected at least one execution_updated notification")
        for payload in exec_payloads:
            self.assertIn("status", payload)
            self.assertIn("execution_id", payload)
            self.assertEqual(payload["agent_id"], self.agent.id)

    def test_log_creation_publishes_log_created_event(self):
        execution = self.env["odoo.agent.execution"].create(
            {
                "name": "Log Live Update Exec",
                "prompt": "Run me.",
                "agent_id": self.agent.id,
                "task_id": self.task.id,
                "company_id": self.env.company.id,
            }
        )
        calls, original = self._capture_sendone()
        try:
            self.env["odoo.agent.log"].create(
                {
                    "execution_id": execution.id,
                    "level": "info",
                    "message": "Streaming in.",
                }
            )
        finally:
            type(self.env["bus.bus"]).__class__._sendone = original

        log_payloads = [
            c["payload"]
            for c in calls
            if c["type"] == "odoo_agent" and c["payload"].get("event") == "log_created"
        ]
        self.assertTrue(log_payloads, "Expected at least one log_created notification")
        for payload in log_payloads:
            self.assertEqual(payload["execution_id"], execution.id)
            self.assertIn("level", payload)
            self.assertIn("message", payload)

    def test_chat_message_publishes_to_agent_channel(self):
        calls, original = self._capture_sendone()
        try:
            self.env["odoo.agent.chat.message"].send_user_message(
                self.agent.id,
                "Hi there.",
                project_task_id=self.task.id,
            )
        finally:
            type(self.env["bus.bus"]).__class__._sendone = original

        chat_payloads = [
            c["payload"]
            for c in calls
            if c["type"] == "odoo_agent" and c["payload"].get("event") == "chat_message_created"
        ]
        self.assertTrue(chat_payloads)
        for payload in chat_payloads:
            self.assertEqual(payload.get("agent_id"), self.agent.id)

import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMcpEndpoint(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.action = cls.env["ir.actions.server"].create(
            {
                "name": "MCP echo",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "state": "code",
                "code": "action = {'echo': env.context.get('mcp_params')}",
            }
        )
        cls.tool = cls.env["odooclaw.mcp.tool"].create(
            {
                "name": "echo",
                "description": "Echo the arguments back.",
                "model_name": "res.partner",
                "action_id": cls.action.id,
                "input_schema": json.dumps(
                    {"type": "object", "properties": {"value": {"type": "string"}}}
                ),
            }
        )
        cls.key = cls.env["odooclaw.mcp.key"].create(
            {"name": "test key", "user_id": cls.env.user.id}
        )
        cls.env.ref("base.user_admin").password = "mcp-test"

    def setUp(self):
        super().setUp()
        self.authenticate("admin", "mcp-test")

    def _post(self, payload, key=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["X-MCP-Key"] = key
        return self.url_open("/mcp", data=json.dumps(payload), headers=headers)

    def test_a_request_without_key_is_refused(self):
        response = self._post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], -32001)

    def test_initialize_and_list_the_tools(self):
        response = self._post(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, self.key.token
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["serverInfo"]["name"], "odooclaw-mcp")

        response = self._post(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.key.token
        )
        names = [tool["name"] for tool in response.json()["result"]["tools"]]
        self.assertIn("echo", names)

    def test_call_the_tool_and_read_its_result(self):
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"value": "hola"}},
            },
            self.key.token,
        )
        data = response.json()
        text = data["result"]["content"][0]["text"]
        self.assertIn("hola", text)

    def test_a_write_tool_needs_the_setting(self):
        write_tool = self.env["odooclaw.mcp.tool"].create(
            {
                "name": "write_echo",
                "description": "Write tool.",
                "action_id": self.action.id,
                "is_write": True,
            }
        )
        response = self._post(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, self.key.token
        )
        names = [tool["name"] for tool in response.json()["result"]["tools"]]
        self.assertNotIn("write_echo", names)

        self.env["ir.config_parameter"].sudo().set_param("odooclaw.mcp.allow_writes", "1")
        response = self._post(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, self.key.token
        )
        names = [tool["name"] for tool in response.json()["result"]["tools"]]
        self.assertIn("write_echo", names)
        write_tool.unlink()

import json
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "odooclaw-mcp", "version": "18.0.1.0.0"}
WRITES_PARAM = "odooclaw.mcp.allow_writes"


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class OdooclawMcpController(http.Controller):
    def _key(self):
        header = request.httprequest.headers.get("X-MCP-Key") or ""
        if not header:
            authorization = request.httprequest.headers.get("Authorization") or ""
            if authorization.lower().startswith("bearer "):
                header = authorization[7:].strip()
        if not header:
            return None
        key = (
            request.env["odooclaw.mcp.key"]
            .sudo()
            .search([("token", "=", header), ("active", "=", True)], limit=1)
        )
        if key:
            try:
                key.sudo().write({"last_used_at": fields.Datetime.now()})
            except Exception:  # noqa: BLE001 - a read-only replica must not break /mcp
                _logger.debug("MCP key last_used_at not updated", exc_info=True)
        return key

    def _writes_allowed(self):
        value = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param(WRITES_PARAM, "0")
        )
        return str(value).lower() in ("1", "true", "yes")

    def _visible_tools(self):
        domain = [("active", "=", True)]
        if not self._writes_allowed():
            domain.append(("is_write", "=", False))
        return request.env["odooclaw.mcp.tool"].sudo().search(domain)

    @http.route(
        "/mcp",
        type="http",
        auth="none",
        csrf=False,
        methods=["POST"],
        save_session=False,
    )
    def mcp(self, **kwargs):
        key = self._key()
        if not key:
            return request.make_json_response(
                _error(None, -32001, "unauthorized"), status=401
            )
        try:
            body = json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except ValueError:
            return request.make_json_response(_error(None, -32700, "parse error"), status=400)

        request_id = body.get("id")
        method = body.get("method") or ""
        params = body.get("params") or {}

        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        elif method == "ping":
            result = {}
        elif method == "notifications/initialized":
            return request.make_json_response({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "tools/list":
            result = {"tools": self._tool_definitions()}
        elif method == "tools/call":
            result = self._call_tool(key, params)
            if isinstance(result, dict) and result.get("__error__"):
                return request.make_json_response(
                    _error(request_id, -32602, result["__error__"])
                )
        else:
            return request.make_json_response(
                _error(request_id, -32601, "method not found"), status=200
            )

        return request.make_json_response(
            {"jsonrpc": "2.0", "id": request_id, "result": result}
        )

    def _tool_definitions(self):
        tools = []
        for tool in self._visible_tools():
            try:
                schema = json.loads(tool.input_schema or "{}")
            except ValueError:
                _logger.warning("Invalid input schema on MCP tool %s", tool.name)
                schema = {"type": "object", "properties": {}}
            tools.append(
                {"name": tool.name, "description": tool.description, "inputSchema": schema}
            )
        return tools

    def _call_tool(self, key, params):
        name = params.get("name")
        arguments = params.get("arguments") or {}
        domain = [("name", "=", name), ("active", "=", True)]
        if not self._writes_allowed():
            domain.append(("is_write", "=", False))
        tool = request.env["odooclaw.mcp.tool"].sudo().search(domain, limit=1)
        if not tool:
            return {"__error__": "unknown tool %s" % name}
        if not tool.action_id:
            return {"__error__": "tool %s has no action" % name}
        action = (
            tool.action_id.with_user(key.user_id).with_context(mcp_params=arguments)
        )
        result = action.run()
        text = json.dumps(result if result is not None else {}, default=str)
        return {"content": [{"type": "text", "text": text}], "isError": False}

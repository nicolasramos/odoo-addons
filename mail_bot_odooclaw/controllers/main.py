from odoo import http, SUPERUSER_ID
from werkzeug.exceptions import HTTPException
from odoo.http import request
import json
from markupsafe import Markup

from ..utils.markdown_html import markdown_to_safe_html
from . import security


def _normalize_x2many_ids(value, field_name):
    """Return a flat list of ints from an id field's payload.

    Odoo's ``mail.thread.message_post`` validates ``attachment_ids`` (and
    ``voice_ids``) as a literal list of ints and raises ``ValueError`` on
    anything else — before the message exists. Measured on Odoo Server 17.0:

        attachment_ids=[(6, 0, [48341])]  -> ValueError, nothing created
        attachment_ids=[48341]            -> message created, attachment linked

    Both shapes are natural for a caller to send: the x2many command form is how
    every other m2m field is written, and it is what the OdooClaw MCP tool layer
    produced. Accept either and hand `message_post` the flat form it requires,
    so neither client has to know this Odoo-internal detail.
    """
    if value is None:
        return []

    # x2many command form: (6, 0, [ids]) / [6, 0, [ids]] — take the last element.
    if (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and value[0] in (6, "6")
        and isinstance(value[2], (list, tuple))
    ):
        value = value[2]

    # A single command wrapped in a list, e.g. [[6, 0, [ids]]].
    if (
        isinstance(value, (list, tuple))
        and len(value) == 1
        and isinstance(value[0], (list, tuple))
        and len(value[0]) == 3
        and value[0][0] in (6, "6")
    ):
        value = value[0][2]

    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]

    if isinstance(value, int):
        return [value]

    raise ValueError(
        "%s must be a list of ids or an x2many command, got %r" % (field_name, value)
    )


class OdooClawController(http.Controller):
    @http.route(
        "/odooclaw/reply", type="http", auth="public", methods=["POST"], csrf=False
    )
    def odooclaw_reply(self, **kwargs):
        """
        Endpoint for OdooClaw to send messages back to an Odoo discussion/thread.
        Supports text messages and voice attachments (voice notes).

        Expected payload:
        {
            "model": "mail.channel",
            "res_id": 123,
            "message": "Hello!",
            "attachment_ids": [456, 457],
            "voice_metadata_ids": [789]
        }
        """
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            model_name = payload.get("model")
            res_id = payload.get("res_id")
            message_body = payload.get("message", "")
            attachment_ids = payload.get("attachment_ids", [])
            voice_metadata_ids = payload.get("voice_metadata_ids", [])
            reply_token = payload.get("reply_token", "")

            if not model_name or not res_id:
                return security.error_response("Missing parameters")

            if not message_body and not attachment_ids:
                return security.error_response("Missing message or attachments")

            # Validate reply token — ensures this reply was solicited by a human message
            if not reply_token:
                return request.make_json_response(
                    {"status": "error", "reason": "Missing reply_token"},
                    status=401
                )
            token_valid = (
                request.env["mail.odooclaw.reply.token"]
                .sudo()
                ._validate(reply_token, model_name, res_id)
            )
            if not token_valid:
                return request.make_json_response(
                    {"status": "error", "reason": "Invalid or expired reply_token"},
                    status=403
                )

            bot_user = (
                request.env["res.users"]
                .sudo()
                .search([("login", "=", "odooclaw_bot")], limit=1)
            )
            if not bot_user:
                return security.error_response("OdooClaw bot user not found")

            message_html = markdown_to_safe_html(message_body)

            post_values = {
                "body": Markup(message_html),
                "author_id": bot_user.partner_id.id,
                "message_type": "comment",
            }

            if attachment_ids:
                post_values["attachment_ids"] = _normalize_x2many_ids(
                    attachment_ids, "attachment_ids"
                )

            if voice_metadata_ids:
                post_values["voice_ids"] = _normalize_x2many_ids(
                    voice_metadata_ids, "voice_metadata_ids"
                )

            record = request.env[model_name].sudo().browse(res_id)
            if record.exists():
                record.with_user(bot_user).sudo().message_post(**post_values)

                if model_name == "mail.channel":
                    channel_partner = request.env["mail.channel.member"].search(
                        [
                            ("channel_id", "=", record.id),
                            ("partner_id", "=", bot_user.partner_id.id),
                        ],
                        limit=1,
                    )
                    if channel_partner:
                        channel_partner._notify_typing(is_typing=False)

                return request.make_json_response({"status": "ok"})

            return security.error_response("Record not found")
        except Exception as e:
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(security._logger, "odooclaw_reply error")

    @http.route(
        "/odooclaw/call_kw_as_user",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def call_kw_as_user(self, **kwargs):
        """
        Executes an ORM method on behalf of a specific user.
        Payload:
        {
            "user_id": 5,
            "model": "sale.order",
            "method": "create",
            "args": [[{...}]],
            "kwargs": {}
        }
        """
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            user_id = payload.get("user_id")
            model = payload.get("model")
            method = payload.get("method")
            args = payload.get("args", [])
            kwargs_dict = payload.get("kwargs", {})
            context_dict = payload.get("context") or {}

            if not user_id or not model or not method:
                return security.error_response("Missing user_id, model, or method")

            if not request.session.uid:
                return security.error_response(
                    "Unauthorized. Must be logged in via session.",
                    status=401,
                )

            caller = request.env.user
            odooclaw_bot = request.env.ref(
                "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
            )
            if not (
                (odooclaw_bot and caller.id == odooclaw_bot.id)
                or caller.has_group("mail_bot_odooclaw.group_odooclaw_delegator")
                or caller.has_group("base.group_system")
            ):
                return security.error_response(
                    "Unauthorized. Delegated RPC permission required.",
                    status=401,
                )

            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                return security.error_response("Invalid user_id")

            target_user = request.env["res.users"].sudo().browse(user_id)
            if user_id == SUPERUSER_ID or not target_user.exists() or not target_user.active:
                return security.error_response("Invalid delegated user")

            if not isinstance(kwargs_dict, dict):
                kwargs_dict = {}
            if not isinstance(context_dict, dict):
                context_dict = {}

            merged_context = dict(request.env.context)
            merged_context.update(context_dict)

            safe_env = request.env(user=user_id, context=merged_context)

            try:
                recs = safe_env[model]
                if args and (
                    isinstance(args[0], int)
                    or (
                        isinstance(args[0], list)
                        and (not args[0] or isinstance(args[0][0], int))
                    )
                ):
                    if method not in (
                        "search",
                        "create",
                        "search_read",
                        "search_count",
                        "fields_get",
                    ):
                        recs = recs.browse(args.pop(0))

                result = getattr(recs, method)(*args, **kwargs_dict)
                if hasattr(result, "_name") and hasattr(result, "ids"):
                    if method in ("create", "message_post") and len(result.ids) == 1:
                        result = result.ids[0]
                    else:
                        result = result.ids
                return request.make_json_response({"status": "ok", "result": result})
            except Exception as orm_error:
                return security.error_response("Odoo ORM error", status=500)

        except Exception as e:
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(security._logger, "call_kw_as_user error")

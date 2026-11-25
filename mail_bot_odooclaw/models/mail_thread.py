import base64
import logging
import requests
import json
import threading
from odoo import models, api, tools, _

# What the engine can read on its own. Anything else is left out on purpose:
# a spreadsheet is not a document the model can look at.
_ODOOCLAW_ATTACHMENT_TYPES = ("image/", "audio/")
_ODOOCLAW_ATTACHMENT_MAX = 3
_ODOOCLAW_ATTACHMENT_MAX_BYTES = 6 * 1024 * 1024
_ODOOCLAW_ATTACHMENT_MAX_TOTAL = 12 * 1024 * 1024

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _resolve_private_reply_channel(self, author_partner, bot_partner):
        Channel = self.env["discuss.channel"].sudo()
        existing = Channel.search(
            [
                ("channel_type", "=", "chat"),
                ("channel_member_ids.partner_id", "=", author_partner.id),
                ("channel_member_ids.partner_id", "=", bot_partner.id),
            ],
            limit=1,
        )
        if existing:
            return existing

        return Channel.create(
            {
                "name": _("Chat with OdooClaw"),
                "channel_type": "chat",
                "channel_member_ids": [
                    (0, 0, {"partner_id": author_partner.id}),
                    (0, 0, {"partner_id": bot_partner.id}),
                ],
            }
        )

    @api.returns("mail.message", lambda value: value.id)
    def message_post(self, **kwargs):
        message = super(MailThread, self).message_post(**kwargs)

        # Determine if OdooClaw is mentioned or it's a direct message to OdooClaw
        odooclaw_user = self.env.ref(
            "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
        )
        if not odooclaw_user:
            return message

        # Prevent infinite loops (don't reply to ourselves)
        if message.author_id == odooclaw_user.partner_id:
            return message

        odooclaw_partner_id = odooclaw_user.partner_id.id
        is_mentioned = odooclaw_partner_id in message.partner_ids.ids

        # If it's a channel, check if it's a DM with OdooClaw
        is_dm = False
        if message.model == "discuss.channel":
            channel = self.env["discuss.channel"].browse(message.res_id)
            if (
                channel.channel_type == "chat"
                and odooclaw_partner_id
                in channel.channel_member_ids.mapped("partner_id").ids
            ):
                is_dm = True

        if is_mentioned or is_dm:
            # We must clean the text (remove html tags usually added by odoo)
            body_text = tools.html2plaintext(message.body)

            # The answer to the proactive invitation. The engine asks once
            # whether the user wants suggestions; a "sí" in the bot's private
            # chat is that answer. It is handled here, before the webhook, so
            # the conversational agent does not also reply to it.
            if is_dm and self._odooclaw_is_optin_reply(body_text):
                self._odooclaw_enable_optin(message)
                return message

            # Process attachments - include voice messages and invoices info
            voice_attachments = []
            invoice_attachments = []
            other_attachments = []

            if message.attachment_ids:
                for att in message.attachment_ids:
                    mimetype = (att.mimetype or "").lower()
                    name = (att.name or "").lower()

                    # Check if it's a voice attachment
                    if att.voice_ids:
                        voice_attachments.append(
                            {"id": att.id, "name": att.name, "mimetype": att.mimetype}
                        )
                        body_text += f"\n🎤 [Nota de voz: {att.name} (ID: {att.id})]\n"
                    # Check if it's a PDF or image (potential invoice)
                    elif (
                        mimetype == "application/pdf"
                        or mimetype.startswith("image/")
                        or name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
                    ):
                        invoice_attachments.append(
                            {"id": att.id, "name": att.name, "mimetype": att.mimetype}
                        )
                        body_text += (
                            f"\n🧾 [Factura/Documento: {att.name} (ID: {att.id})]\n"
                        )
                    else:
                        other_attachments.append(
                            {"id": att.id, "name": att.name, "mimetype": att.mimetype}
                        )
                        body_text += f"\n[Adjunto: {att.name} (ID: {att.id})]\n"

            # Send webhook asynchronously
            payload = {
                "message_id": message.id,
                "model": message.model,
                "res_id": message.res_id,
                "reply_model": message.model,
                "reply_res_id": message.res_id,
                "author_id": message.author_id.id,
                "author_user_id": message.author_id.user_ids[:1].id or False,
                "author_name": message.author_id.name,
                "body": body_text,
                "is_dm": is_dm,
                "company_id": self.env.company.id,
                "allowed_company_ids": self.env.context.get("allowed_company_ids", []),
                "voice_attachments": voice_attachments,
                "invoice_attachments": invoice_attachments,
                "attachments": other_attachments,
            }

            if not is_dm and message.model == "discuss.channel":
                channel = self.env["discuss.channel"].browse(message.res_id)
                if channel.channel_type == "chat":
                    # Existing 1-to-1 chat: keep private reply behaviour
                    private_channel = self._resolve_private_reply_channel(
                        message.author_id, odooclaw_user.partner_id
                    )
                    payload["reply_model"] = "discuss.channel"
                    payload["reply_res_id"] = private_channel.id
                # else: group channel → reply in the same channel (reply_model/res_id unchanged)

            # Build chatter context: read messages in reverse chronological order,
            # stopping at the last OdooClaw intervention. This gives OdooClaw
            # visibility into what happened between its last reply and now.
            chatter_context = []
            if not is_dm and payload["reply_model"] != "discuss.channel":
                for ctx_msg in self.env["mail.message"].sudo().search([
                    ("model", "=", payload["reply_model"]),
                    ("res_id", "=", payload["reply_res_id"]),
                    ("message_type", "in", ["comment", "email"]),
                    ("id", "!=", message.id),
                ], order="date desc"):
                    if ctx_msg.author_id == odooclaw_user.partner_id:
                        break
                    chatter_context.append({
                        "date": ctx_msg.date.isoformat(),
                        "author": ctx_msg.author_id.name,
                        "body": tools.html2plaintext(ctx_msg.body),
                    })
                chatter_context.reverse()
            payload["chatter_context"] = chatter_context

            # We use threading to not block the current transaction

            # Generate reply token — allows OdooClaw to identify solicited replies
            reply_token_rec = self.env["mail.odooclaw.reply.token"].sudo()._generate(
                model=payload["reply_model"],
                res_id=payload["reply_res_id"],
                message_id=message.id,
            )
            payload["reply_token"] = reply_token_rec.token

            webhook_url = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo")
            )

            webhook_token = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("odooclaw.webhook_token", "")
            )

            def send_webhook(url, data, token):
                try:
                    headers = {"Content-Type": "application/json"}
                    if token:
                        headers["X-OdooClaw-Token"] = token
                    response = requests.post(url, json=data, headers=headers, timeout=5)
                    if response.status_code == 401:
                        _logger.error("OdooClaw rejected webhook: invalid token for %s", url)

                except Exception as e:
                    _logger.error("Failed to send webhook to OdooClaw: %s", str(e))

            threaded_call = threading.Thread(
                target=send_webhook, args=(webhook_url, payload, webhook_token)
            )
            threaded_call.start()

            # Trigger "typing..." indicator if it's a discuss channel
            if message.model == "discuss.channel":
                channel = self.env["discuss.channel"].browse(message.res_id)
                bot_member = channel.channel_member_ids.filtered(
                    lambda m: m.partner_id.id == odooclaw_partner_id
                )
                if bot_member:
                    bot_member.sudo()._notify_typing(is_typing=True)

        # Operational pipeline: any comment from someone other than the bot on a
        # record whose model has a pipeline is work for the engine. Notes are
        # internal and never leave the instance; discuss messages took the
        # branch above and are not business records.
        if message.author_id != odooclaw_user.partner_id:
            self._odooclaw_trigger_pipeline(message, odooclaw_user)

        return message

    def _odooclaw_trigger_pipeline(self, message, bot_user):
        """Queue a customer message for the area's pipeline in the engine.

        The run row is written *before* the network call on purpose: if the
        engine is down, the decision is still on record with its reason, and the
        run stays ``queued`` instead of vanishing.
        """
        if not message.model or message.model.startswith(("mail.", "discuss.")):
            return
        comment = self.env.ref("mail.mt_comment", raise_if_not_found=False)
        if not comment or message.subtype_id != comment:
            return
        pipeline = (
            self.env["mail.odooclaw.pipeline"]
            .sudo()
            .search(
                [
                    ("model_name", "=", message.model),
                    ("enabled", "=", True),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )
        if not pipeline:
            return
        record = self.env[message.model].sudo().browse(message.res_id)
        if not record.exists():
            return
        stage = record.stage_id if "stage_id" in record._fields else record.browse()
        stage_id = stage.id if stage else 0
        stage_name = stage.name if stage else ""
        mode = pipeline.mode_for_stage(stage_id)
        escalate = pipeline.escalate_for_stage(stage_id)
        rule = pipeline.stage_rule_ids.filtered(
            lambda r: r.active and r.stage_id == stage_id
        )[:1]
        template = (rule.template_id if rule else False) or pipeline.template_id
        template_body = ""
        if template:
            # The template is a starting point, not a contract: render it with
            # this record when possible and fall back to its raw text. The agent
            # reads it as a structure, not as a literal reply.
            try:
                rendered = template._render_field("body_html", [record.id])[record.id]
                template_body = tools.html2plaintext(rendered or "")
            except Exception:  # noqa: BLE001
                template_body = tools.html2plaintext(
                    getattr(template, "body_html", "") or ""
                )
            template_body = template_body[:4000]
        run = (
            self.env["mail.odooclaw.pipeline.run"]
            .sudo()
            .create(
                {
                    "pipeline_id": pipeline.id,
                    "model_name": message.model,
                    "res_id": message.res_id,
                    "res_name": record.display_name,
                    "message_id": message.id,
                    "stage_id": stage_id,
                    "stage_name": stage_name,
                    "mode": mode,
                    "state": "queued",
                    "decision": _(
                        "Message from %(author)s received; mode %(mode)s.",
                        author=message.author_id.name or _("unknown"),
                        mode=mode,
                    ),
                }
            )
        )
        icp = self.env["ir.config_parameter"].sudo()
        job_url = icp.get_param(
            "odooclaw.pipeline_url", "http://odooclaw:18790/odooclaw/job"
        )
        token = icp.get_param("odooclaw.reply_token", "")
        payload = {
            "run_id": run.id,
            "pipeline_id": pipeline.id,
            "area": pipeline.area_id.area,
            "model": message.model,
            "res_id": message.res_id,
            "res_name": record.display_name,
            "message_id": message.id,
            "message_body": tools.html2plaintext(message.body or "")[:4000],
            "author_id": message.author_id.id,
            "author_name": message.author_id.name,
            "stage_id": stage_id,
            "stage_name": stage_name,
            "mode": mode,
            "escalate": escalate,
            "escalate_user_id": pipeline.escalate_user_id.id or 0,
            "escalate_after": pipeline.escalate_after,
            "template_id": template.id if template else 0,
            "template_body": template_body,
            "instructions": pipeline.instructions or "",
            "stage_instructions": pipeline.stage_instructions(stage_id),
            "use_knowledge": bool(pipeline.use_knowledge),
            "bot_user_id": bot_user.id,
            "attachments": self._odooclaw_message_attachments(message),
        }

        def send_job(url, data, headers, run_id):
            try:
                response = requests.post(url, json=data, headers=headers, timeout=5)
                if response.status_code >= 400:
                    _logger.warning(
                        "odooclaw: pipeline job rejected (%s) for run %s",
                        response.status_code,
                        run_id,
                    )
            except Exception:
                _logger.warning(
                    "odooclaw: pipeline job failed for run %s", run_id, exc_info=True
                )

        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-OdooClaw-Token"] = token
        threading.Thread(
            target=send_job, args=(job_url, payload, headers, run.id), daemon=True
        ).start()
        return run

    def _odooclaw_message_attachments(self, message):
        """The image and voice attachments of a message, base64 encoded.

        The engine turns them into text before the agent answers: a picture is
        read by the multimodal model, a voice note is transcribed. The cap is
        deliberate; a huge file would sit in the queue for minutes.
        """
        result = []
        total = 0
        for attachment in message.attachment_ids:
            mimetype = (attachment.mimetype or "").lower()
            if not mimetype.startswith(_ODOOCLAW_ATTACHMENT_TYPES):
                continue
            if not attachment.raw:
                continue
            if attachment.file_size and attachment.file_size > _ODOOCLAW_ATTACHMENT_MAX_BYTES:
                continue
            if len(result) >= _ODOOCLAW_ATTACHMENT_MAX:
                break
            data = base64.b64encode(attachment.raw).decode()
            total += len(data)
            if total > _ODOOCLAW_ATTACHMENT_MAX_TOTAL:
                break
            result.append(
                {
                    "name": attachment.name or "adjunto",
                    "mimetype": mimetype,
                    "data": data,
                }
            )
        return result

    # The invitation asks one question. These are the answers that count as a
    # yes; anything else leaves the user uninvited, which fails closed.
    _ODOOCLAW_OPTIN_YES = {
        "si",
        "sí",
        "yes",
        "ok",
        "vale",
        "claro",
        "activalo",
        "actívalo",
        "activa",
        "activar",
        "adelante",
        "de acuerdo",
        "por supuesto",
        "si por favor",
        "sí por favor",
        "si, por favor",
        "sí, por favor",
        "venga",
        "perfecto",
    }

    def _odooclaw_is_optin_reply(self, body_text):
        text = (body_text or "").strip().lower()
        text = text.strip(" .,!¡¿?")
        return text in self._ODOOCLAW_OPTIN_YES

    def _odooclaw_enable_optin(self, message):
        """Report the acceptance to the proactive engine and confirm in chat.

        The opt-in lives in the engine, not here: Odoo decides WHO may be
        offered help, the engine decides WHEN and remembers the answer.
        """
        user = message.author_id.user_ids[:1]
        if not user:
            return
        proactive_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.proactive_url", "")
        )
        if not proactive_url:
            _logger.warning(
                "odooclaw: opt-in received but odooclaw.proactive_url is not set"
            )
            return

        base = proactive_url.rsplit("/signal", 1)[0]
        token = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.reply_token", "")
        )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-OdooClaw-Token"] = token
        try:
            requests.post(
                base + "/optin",
                json={"user_id": user.id},
                headers=headers,
                timeout=5,
            )
        except Exception:  # noqa: BLE001 - the confirmation below is still useful
            _logger.warning(
                "odooclaw: opt-in call failed at %s", base + "/optin", exc_info=True
            )

        bot_user = self.env.ref(
            "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
        )
        if not bot_user:
            return
        # Posting as the bot re-enters this method with author == bot, which
        # returns early: no webhook, no loop.
        self.env["discuss.channel"].browse(message.res_id).with_user(
            bot_user
        ).sudo().message_post(
            body=_(
                "Sugerencias activadas. Te avisaré cuando vea algo útil en la "
                "pantalla en la que estés."
            ),
            author_id=bot_user.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

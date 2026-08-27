import logging
import requests
from odoo import models, api, tools, _

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    @api.model
    def _send_odooclaw_webhook(self, payload, webhook_url, webhook_token):
        """Deliver a committed Discuss event without exposing sensitive data in logs."""
        headers = {"Content-Type": "application/json"}
        if webhook_token:
            headers["X-OdooClaw-Token"] = webhook_token

        log_values = {
            "message_id": payload["message_id"],
            "model": payload["model"],
            "res_id": payload["res_id"],
        }
        try:
            response = requests.post(
                webhook_url, json=payload, headers=headers, timeout=5
            )
        except Exception as error:
            _logger.error(
                "OdooClaw webhook transport failure "
                "message_id=%(message_id)s model=%(model)s res_id=%(res_id)s error=%(error)s",
                {**log_values, "error": type(error).__name__},
            )
            return

        if 200 <= response.status_code < 300:
            _logger.info(
                "OdooClaw webhook delivered "
                "message_id=%(message_id)s model=%(model)s res_id=%(res_id)s status=%(status)s",
                {**log_values, "status": response.status_code},
            )
            return

        _logger.warning(
            "OdooClaw webhook rejected "
            "message_id=%(message_id)s model=%(model)s res_id=%(res_id)s status=%(status)s",
            {**log_values, "status": response.status_code},
        )

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

    def message_post(self, **kwargs):
        """Forward Odoo 19's keyword-only ``message_post`` API unchanged."""
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

            # The token and message must be visible to the reply endpoint first.
            # Post-commit callbacks are discarded automatically on rollback.
            self.env.cr.postcommit.add(
                lambda: self._send_odooclaw_webhook(
                    payload, webhook_url, webhook_token
                )
            )

            # Trigger "typing..." indicator if it's a discuss channel
            if message.model == "discuss.channel":
                channel = self.env["discuss.channel"].browse(message.res_id)
                bot_member = channel.channel_member_ids.filtered(
                    lambda m: m.partner_id.id == odooclaw_partner_id
                )
                if bot_member:
                    bot_member.sudo()._notify_typing(is_typing=True)

        return message

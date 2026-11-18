# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Document intake: every arriving document is declared before anything happens.

This model is the single audit point of the document-intake feature (SDD
``document-intake``, NRA-4497 / T3). Three properties define it:

* **Declaration before processing.** A document that arrives always gets a row
  here — even when every flow switch is off. A disabled flow keeps the document
  traceable (``state='disabled'`` + ``reason``) instead of losing it, so the
  customer can answer "what arrived and why did nothing happen?" from the UI,
  without reading server logs (R8).
* **Fail-closed switches (D7).** ``odooclaw.intake.<flow>.enabled`` ships as
  ``False`` for invoice, contact, expense and mailbox. Turning a flow on is an
  explicit customer action, never the defect. A malformed switch value is read
  as off, never as on.
* **The destination is never created here.** The ocr-invoice skill creates the
  ``account.move`` / ``hr.expense`` / ``res.partner`` and writes the outcome
  back through ``mark_created`` / ``mark_review`` / ``mark_error`` /
  ``mark_duplicate``. The intake only ever *declares* and *records*.

Internal API contract for T6-T11 (stable):

* ``create_for_attachment(attachment, *, intake_type, source, message, actor,
  company)`` — the single entry point for every trigger (chatter, Discuss,
  record, mailbox). Always returns a row. ``state == 'disabled'`` means: stop,
  nothing may be created for this document. ``state == 'duplicate'`` means:
  stop, the same bytes were already declared inside the dedupe window and
  ``duplicate_of_id`` points at the first delivery. ``state == 'new'`` means:
  queue it.
* ``flow_enabled(flow)`` — one of ``invoice`` / ``contact`` / ``expense`` /
  ``mailbox``.
* ``_find_previous(checksum, intake_type=None)`` — dedupe lookup inside the
  configured window; ``intake_type=None`` matches any type (the declaration
  gate dedupes by bytes). The checksum carries its own index because
  ``ir.attachment.checksum`` does not (R-D7).
* ``_is_rate_limited()`` — R10 vision budget; when true the caller queues and
  warns, it does not reject.
* ``mark_processing`` / ``mark_created`` / ``mark_review`` / ``mark_error`` /
  ``mark_duplicate`` — the write-back door for the skill.
"""

import json
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_PREFIX = "odooclaw.intake."

# intake_type -> flow switch. "mailbox" is a switch of its own: it gates the
# email source regardless of the document type (design D-B1).
TYPE_TO_FLOW = {"invoice": "invoice", "expense": "expense", "contact": "contact"}
DOCUMENT_FLOWS = ("invoice", "contact", "expense")
ALL_FLOWS = ("invoice", "contact", "expense", "mailbox")

# Only an explicit truthy value enables a flow. bool("False") is True in
# Python — never use bare truthiness on a config string here (fail-closed).
TRUE_VALUES = ("true", "1", "yes", "on")


class OdooclawDocumentIntake(models.Model):
    _name = "odooclaw.document.intake"
    _description = "OdooClaw document intake"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    # -- Provenance: where the document came from (R8) ----------------------
    source = fields.Selection(
        [
            ("chatter", "Chatter"),
            ("discuss", "Discuss"),
            ("record", "Record"),
            ("mailbox", "Mailbox"),
        ],
        required=True,
        default="chatter",
        index=True,
    )
    attachment_id = fields.Many2one(
        "ir.attachment", string="Attachment", ondelete="set null", index=True
    )
    filename = fields.Char(readonly=True)
    mimetype = fields.Char(readonly=True)
    checksum = fields.Char(
        readonly=True,
        index=True,
        help="sha1 of the attachment binary (the native ir.attachment "
        "checksum). Indexed here on purpose: the native column is not "
        "indexed and scanning it at volume is a sequential scan (R-D7).",
    )
    message_id = fields.Many2one(
        "mail.message", string="Source Message", ondelete="set null"
    )
    actor_id = fields.Many2one(
        "res.partner", string="Delivered By", ondelete="set null"
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )

    # -- Classification and lifecycle ---------------------------------------
    intake_type = fields.Selection(
        [
            ("invoice", "Invoice"),
            ("expense", "Expense"),
            ("contact", "Contact"),
            ("unknown", "Unknown"),
        ],
        required=True,
        default="unknown",
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("processing", "Processing"),
            ("created", "Created"),
            ("review", "Review"),
            ("duplicate", "Duplicate"),
            ("superseded", "Superseded"),
            ("error", "Error"),
            ("disabled", "Disabled"),
        ],
        required=True,
        default="new",
        tracking=True,
        index=True,
        copy=False,
    )

    # -- Extraction report (written back by the pipeline) --------------------
    confidence = fields.Float(
        help="Global extraction confidence (0..1) as reported by the pipeline."
    )
    field_confidence = fields.Json(
        string="Field Confidence",
        help="Per-field confidence map reported by the pipeline (R6).",
    )
    missing_fields = fields.Text(
        string="Missing Fields",
        help="What could not be read, in plain language. A field that was not "
        "read is absent from the destination record — never invented (R6).",
    )
    reason = fields.Text(
        help="Why the document was disabled, sent to review, or failed."
    )
    issues = fields.Text(
        help="Raw _issues emitted by the extraction pipeline, stored without "
        "reinterpretation."
    )

    # -- Destination (empty whenever nothing was created) --------------------
    created_model = fields.Char(
        help="Model of the record created for this document. Empty means "
        "nothing was created: the intake only declares and records."
    )
    created_res_id = fields.Integer(help="Id of the record created.")
    duplicate_of_id = fields.Many2one(
        "odooclaw.document.intake",
        string="Duplicate Of",
        ondelete="set null",
        index=True,
    )
    duplicate_ids = fields.One2many(
        "odooclaw.document.intake", "duplicate_of_id", string="Duplicates"
    )
    processed_by = fields.Selection(
        [("odooclaw", "OdooClaw"), ("standard", "Standard Odoo")],
        required=True,
        default="odooclaw",
        help="Which engine handled this document. The mailbox evidence (T11) "
        "rests on this field: 'odooclaw' proves the standard Odoo mail flow "
        "did not create the record.",
    )

    # -- Parameters (ir.config_parameter, fail-closed) -----------------------
    @api.model
    def _param(self, key, default=None):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_PREFIX + key)
        if raw is None or not str(raw).strip():
            return default
        return str(raw).strip()

    @api.model
    def _param_bool(self, key, default=False):
        raw = self._param(key)
        if raw is None:
            return default
        return raw.lower() in TRUE_VALUES

    @api.model
    def _param_float(self, key, default=0.0):
        raw = self._param(key)
        try:
            return float(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    @api.model
    def _param_int(self, key, default=0):
        raw = self._param(key)
        try:
            return int(float(raw)) if raw is not None else default
        except (TypeError, ValueError):
            return default

    @api.model
    def flow_enabled(self, flow):
        """Whether one intake flow is switched on.

        ``odooclaw.intake.<flow>.enabled`` with ``<flow>`` in invoice, contact,
        expense, mailbox. Anything that is not an explicit truthy value —
        missing, empty, malformed — means off (D7).
        """
        return self._param_bool(f"{flow}.enabled")

    # -- The gate -------------------------------------------------------------
    @api.model
    def _gate_reason(self, intake_type, source):
        """Why this document must not be processed, or ``None`` if a flow is on.

        The gate is evaluated at declaration time so the row carries the reason
        the customer can read in the review queue. An ``unknown`` type can only
        be classified if at least one document flow is on.
        """
        if source == "mailbox" and not self.flow_enabled("mailbox"):
            return _(
                "The mailbox intake flow is disabled "
                "(odooclaw.intake.mailbox.enabled)."
            )
        flow = TYPE_TO_FLOW.get(intake_type)
        if flow is not None:
            if self.flow_enabled(flow):
                return None
            return _(
                "The %(flow)s intake flow is disabled "
                "(odooclaw.intake.%(flow)s.enabled).",
                flow=flow,
            )
        if any(self.flow_enabled(candidate) for candidate in DOCUMENT_FLOWS):
            return None
        return _("All document intake flows are disabled.")

    # -- The single entry point -------------------------------------------------
    @api.model
    def create_for_attachment(
        self,
        attachment,
        *,
        intake_type="unknown",
        source="chatter",
        message=None,
        actor=None,
        company=None,
    ):
        """Declare one arriving document and return its intake row.

        Every trigger (chatter/Discuss mention, attachment on a record, the
        mailbox gateway) goes through here, so the declaration rules cannot
        drift between them. The row is created with ``sudo()`` because the
        mail gateway runs without a human grant; visibility of the queue
        itself is governed by ir.model.access.

        Contract for the flows: ``state == 'disabled'`` -> stop, nothing may be
        created for this document; ``state == 'new'`` -> queue it for the
        pipeline.
        """
        vals = {
            "source": source,
            "attachment_id": attachment.id,
            "filename": attachment.name or "",
            "mimetype": attachment.mimetype or "",
            "checksum": attachment.checksum or False,
            "message_id": message.id if message else False,
            "actor_id": (actor or self.env.user.partner_id).id,
            "company_id": (company or self.env.company).id,
            "intake_type": intake_type,
        }
        gate_reason = self._gate_reason(intake_type, source)
        if gate_reason:
            vals.update({"state": "disabled", "reason": gate_reason})
        else:
            # R7 idempotency (T10): the same bytes delivered inside the
            # window are the same document. The copy is declared as
            # ``duplicate`` linked to the first, and the pipeline contract
            # only processes ``new`` — so nothing is ever created twice.
            # The false positive (two legitimate deliveries of the same
            # file) is resolved by hand via ``action_dismiss_duplicate``;
            # nothing is created automatically "just in case".
            original = self._find_previous(vals["checksum"])
            if original:
                vals.update(
                    {
                        "state": "duplicate",
                        "duplicate_of_id": original.id,
                        "reason": _(
                            "Duplicate of intake #%s: the same file was "
                            "received within the last %s days. Nothing was "
                            "created twice. Use \"Dismiss duplicate\" if "
                            "this is a false positive (two legitimate "
                            "deliveries of the same file).",
                            original.id,
                            self._param_int("dedupe_days", 30),
                        ),
                    }
                )
        return self.sudo().create(vals)

    # -- Dedupe and budget helpers (policy lives in T10 / T9) -------------------
    @api.model
    def _find_previous(self, checksum, intake_type=None, window_days=None):
        """Most recent declared document with the same bytes.

        Inside the configured window (``odooclaw.intake.dedupe_days``,
        default 30). ``intake_type=None`` matches any type: the declaration
        gate dedupes by bytes — the same file is the same document whatever
        type the pipeline later assigns. Pass a type to scope the lookup to
        one destination (the pipeline's pre-create check, T6-T9).

        Intakes that declared nothing (``disabled``, ``error``) never shadow
        a later delivery: there is no destination record to duplicate.
        ``duplicate`` never shadows either, so every copy links to the
        original instead of chaining; ``superseded`` (a dismissed false
        positive) stops shadowing for good. A window of ``0`` days
        switches dedupe off entirely.
        """
        if not checksum:
            return self.browse()
        if window_days is None:
            window_days = max(self._param_int("dedupe_days", 30), 0)
        if window_days <= 0:
            # A zero (or negative) window means dedupe is switched off:
            # every delivery is processed. Comparing against a same-second
            # cutoff would still match, which is not "no window".
            return self.browse()
        cutoff = fields.Datetime.now() - timedelta(days=window_days)
        domain = [
            ("checksum", "=", checksum),
            ("state", "not in", ("disabled", "error", "duplicate", "superseded")),
            ("create_date", ">=", cutoff),
        ]
        if intake_type:
            domain.append(("intake_type", "=", intake_type))
        return self.sudo().search(domain, order="id desc", limit=1)

    @api.model
    def _is_rate_limited(self):
        """R10: has the vision budget for the last hour been reached?

        Disabled intakes never reach the pipeline, so they do not burn the
        budget. When this returns True the caller ENCOLAS (the row stays
        ``new``) and warns — it does not reject (R10).
        """
        limit = self._param_int("max_per_hour", 60)
        if limit <= 0:
            return False
        cutoff = fields.Datetime.now() - timedelta(hours=1)
        counted = self.sudo().search_count(
            [("create_date", ">=", cutoff), ("state", "!=", "disabled")]
        )
        return counted >= limit

    # -- Write-back door for the pipeline (T6-T9) --------------------------------
    def _set_state(self, state):
        """Single door to state transitions: a typo cannot become a silent state."""
        valid = dict(self._fields["state"].selection)
        if state not in valid:
            raise ValueError(f"unknown intake state {state!r}")
        self.ensure_one()
        self.state = state

    def _apply_report(self, vals, confidence, field_confidence, issues):
        if confidence is not None:
            vals["confidence"] = float(confidence)
        if field_confidence is not None:
            vals["field_confidence"] = field_confidence
        if issues is not None:
            vals["issues"] = (
                issues if isinstance(issues, str) else json.dumps(issues, ensure_ascii=False)
            )
        self.write(vals)

    def mark_processing(self):
        """The pipeline has picked this document up."""
        self.ensure_one()
        self._set_state("processing")

    def mark_created(self, created_model, created_res_id, confidence=None,
                     field_confidence=None, issues=None):
        """Record the destination created for this document (R8).

        The first mark also leaves the UI evidence (T11): a note on the
        destination's chatter and one here. A retry repeating the same
        outcome stays silent — the chatter must not fill with duplicates.
        """
        self.ensure_one()
        created_res_id = int(created_res_id)
        repeat = (
            self.state == "created"
            and self.created_model == created_model
            and self.created_res_id == created_res_id
        )
        vals = {"created_model": created_model, "created_res_id": created_res_id}
        self._apply_report(vals, confidence, field_confidence, issues)
        self._set_state("created")
        if not repeat:
            self._post_intake_created_trace()
            self._post_destination_trace()

    def mark_review(self, reason, missing_fields=None, confidence=None,
                    field_confidence=None, issues=None):
        """Nothing was created: the document waits in the review queue (R6).

        The reason is also posted to the chatter (T11): the review queue
        must tell why the document is there without opening the field.
        """
        self.ensure_one()
        repeat = self.state == "review" and self.reason == reason
        vals = {"reason": reason}
        if missing_fields:
            vals["missing_fields"] = missing_fields
        self._apply_report(vals, confidence, field_confidence, issues)
        self._set_state("review")
        if not repeat:
            self._post_intake_note(Markup(_("Sent to the review queue: %s")) % (reason or ""))

    def mark_error(self, reason):
        """Processing failed in a way the customer must see (not a silent log line)."""
        self.ensure_one()
        repeat = self.state == "error" and self.reason == reason
        self.write({"reason": reason})
        self._set_state("error")
        if not repeat:
            self._post_intake_note(Markup(_("Processing failed: %s")) % (reason or ""))

    # -- UI evidence (T11): the marks must be seen, not just stored ------------

    def _bot_partner(self):
        """The OdooClaw bot's partner, used as the author of every trace so
        the chatter attribution is the system, not the pipeline session."""
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        return bot.partner_id if bot else self.env["res.partner"]

    def _created_record(self):
        """The destination record, or ``None`` when it cannot be resolved.

        ``created_model`` is free text written back by the pipeline: it may
        name a model that is not installed, and the record may have been
        deleted since. Evidence must never raise on top of that.
        """
        self.ensure_one()
        Model = self.env.get(self.created_model or "")
        if Model is None or not self.created_res_id:
            return None
        return Model.sudo().browse(self.created_res_id).exists() or None

    def _intake_link(self):
        return Markup(
            '<a href="#" data-oe-model="odooclaw.document.intake" data-oe-id="%s">%s</a>'
        ) % (self.id, _("intake #%s", self.id))

    def _post_intake_note(self, body):
        bot_partner = self._bot_partner()
        self.message_post(
            body=body,
            author_id=bot_partner.id or None,
            subtype_xmlid="mail.mt_note",
        )

    def _post_intake_created_trace(self):
        self.ensure_one()
        if self.confidence:
            text = _(
                "Created %(model)s #%(id)s from this document. "
                "Confidence: %(conf)s.",
                model=self.created_model,
                id=self.created_res_id,
                conf=f"{self.confidence * 100:.0f}%",
            )
        else:
            text = _(
                "Created %(model)s #%(id)s from this document.",
                model=self.created_model,
                id=self.created_res_id,
            )
        self._post_intake_note(Markup("%(text)s") % {"text": text})

    def _post_destination_trace(self):
        """Chatter note on the created record (T11).

        This is the business user's evidence: opening the expense, bill or
        contact shows that OdooClaw — not the standard mail flow — created
        it, with the document, the sender and the confidence behind it.
        Posted as the bot, as an internal note, and best-effort by
        contract: a missing destination must never break the write-back
        door (the Go side already treats this call as non-fatal).
        """
        self.ensure_one()
        try:
            record = self._created_record()
            if record is None or not hasattr(record, "message_post"):
                return
            bot_partner = self._bot_partner()
            line1 = Markup(_("Created by OdooClaw from the document %s.")) % (
                Markup("<i>%s</i>") % (self.filename or "")
            )
            line2 = Markup(_("Delivered by %s.")) % (
                Markup("<b>%s</b>") % (self.actor_id.display_name or _("unknown sender"))
            )
            line3 = (
                Markup(_("Confidence: %s.")) % f"{self.confidence * 100:.0f}%"
                if self.confidence
                else Markup("")
            )
            line4 = Markup(_("Full report: %s.")) % self._intake_link()
            record.message_post(
                body=Markup("<p>%s</p><p>%s<br/>%s<br/>%s</p>") % (line1, line2, line3, line4),
                author_id=bot_partner.id or None,
                subtype_xmlid="mail.mt_note",
            )
        except Exception:
            _logger.warning(
                "OdooClaw intake #%s: could not post the creation trace on %s #%s",
                self.id,
                self.created_model,
                self.created_res_id,
                exc_info=True,
            )

    def action_view_created_record(self):
        """Open the record this document produced (T11 navigation): the
        review queue must reach its destination in one click."""
        self.ensure_one()
        record = self._created_record()
        if record is None:
            raise UserError(
                _(
                    "The record created from this document is no longer "
                    "available (%(model)s #%(id)s).",
                    model=self.created_model or _("none"),
                    id=self.created_res_id or 0,
                )
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": self.created_model,
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
            "name": record.display_name,
        }

    def mark_duplicate(self, original):
        """Link this intake to the original it duplicates (R7, policy in T10)."""
        self.ensure_one()
        self.write({"duplicate_of_id": original.id})
        self._set_state("duplicate")

    def action_dismiss_duplicate(self):
        """Resolve a false-positive duplicate by hand (design §3.7).

        Two legitimate deliveries of the same bytes — two photos of the
        same ticket, twin invoices — must both be able to exist. Nothing
        is created automatically "just in case": this action only resets
        the state contract. The dismissed copy goes back to ``new`` so the
        pipeline processes it as a normal delivery, and the original is
        marked ``superseded`` so it stops shadowing future copies.
        Creation itself stays the pipeline's job (T6-T9).
        """
        self.ensure_one()
        if self.state != "duplicate":
            raise UserError(
                _("Only a duplicate intake can be dismissed; this one is %s.",
                  self.state)
            )
        original = self.duplicate_of_id
        self.write({"duplicate_of_id": False, "reason": False})
        self._set_state("new")
        self.message_post(
            body=_(
                "Duplicate dismissed: this document will be processed as a "
                "new delivery."
            )
        )
        if original:
            original._set_state("superseded")
            original.message_post(
                body=_(
                    "Superseded: intake #%s carrying the same file was "
                    "dismissed as a false positive and is processed instead.",
                    self.id,
                )
            )

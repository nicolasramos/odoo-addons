from datetime import timedelta
import json

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..controllers import main as main_controller
from ..controllers import security
from .request_mock import FakeRequest, patch_request


@tagged("post_install", "-at_install")
class TestMailOdooClawReplyToken(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Token = self.env["mail.odooclaw.reply.token"]
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.reply_token_ttl", "300"
        )
        # The controller runs security.authorize() first, which default-denies
        # unless a credential is configured; the URL client is the loopback.
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.allowed_ips", "127.0.0.1"
        )

    def _make_token(self, token="test-uuid-1234", model="crm.lead", res_id=1,
                    offset_seconds=300, used=False):
        return self.Token.sudo().create({
            "token": token,
            "model": model,
            "res_id": res_id,
            "expiry": fields.Datetime.now() + timedelta(seconds=offset_seconds),
            "used": used,
        })

    # --- _generate() ---

    def test_generate_uses_config_ttl(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.reply_token_ttl", "120"
        )
        rec = self.Token.sudo()._generate("crm.lead", 42, False)
        delta = (rec.expiry - fields.Datetime.now()).total_seconds()
        self.assertAlmostEqual(delta, 120, delta=5)

    def test_generate_default_ttl_when_unset(self):
        self.env["ir.config_parameter"].sudo().search(
            [("key", "=", "odooclaw.reply_token_ttl")]
        ).unlink()
        rec = self.Token.sudo()._generate("crm.lead", 42, False)
        delta = (rec.expiry - fields.Datetime.now()).total_seconds()
        self.assertAlmostEqual(delta, 300, delta=5)

    # --- _validate() ---

    def test_validate_valid_token(self):
        self._make_token()
        result = self.Token.sudo()._validate("test-uuid-1234", "crm.lead", 1)
        self.assertTrue(result)

    def test_validate_single_use(self):
        self._make_token()
        self.assertTrue(self.Token.sudo()._validate("test-uuid-1234", "crm.lead", 1))
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "crm.lead", 1))

    def test_validate_expired_token(self):
        self._make_token(offset_seconds=-1)
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "crm.lead", 1))

    def test_validate_wrong_model(self):
        self._make_token()
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "sale.order", 1))

    def test_validate_wrong_res_id(self):
        self._make_token()
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "crm.lead", 99))

    def test_validate_missing_token(self):
        self.assertFalse(self.Token.sudo()._validate("", "crm.lead", 1))

    # --- _cleanup_expired() ---

    def test_cleanup_removes_expired(self):
        self._make_token(token="expired", offset_seconds=-1)
        self.Token.sudo()._cleanup_expired()
        self.assertFalse(self.Token.sudo().search([("token", "=", "expired")]))

    def test_cleanup_removes_used(self):
        self._make_token(token="used", used=True)
        self.Token.sudo()._cleanup_expired()
        self.assertFalse(self.Token.sudo().search([("token", "=", "used")]))

    def test_cleanup_keeps_active(self):
        self._make_token(token="active")
        self.Token.sudo()._cleanup_expired()
        self.assertTrue(self.Token.sudo().search([("token", "=", "active")]))

    # --- Controller ---

    def _call_reply(self, payload):
        """Run the reply route with a fake request bound to this transaction."""
        fake = FakeRequest(self.env, payload=payload)
        with patch_request(fake, main_controller, security):
            return main_controller.OdooClawController().odooclaw_reply()

    def test_controller_no_token_rejected(self):
        resp = self._call_reply(
            {"model": "crm.lead", "res_id": 1, "message": "hi"}
        )
        data = json.loads(resp.data)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(data["reason"], "Missing reply_token")

    def test_controller_expired_token_rejected(self):
        rec = self._make_token(offset_seconds=-1)
        resp = self._call_reply(
            {
                "model": "crm.lead",
                "res_id": 1,
                "message": "hi",
                "reply_token": rec.token,
            }
        )
        data = json.loads(resp.data)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data["reason"], "Invalid or expired reply_token")

    def test_controller_valid_token_passes_validation(self):
        rec = self._make_token()
        resp = self._call_reply(
            {
                "model": "crm.lead",
                "res_id": 1,
                "message": "hi",
                "reply_token": rec.token,
            }
        )
        data = json.loads(resp.data)
        self.assertNotEqual(data.get("reason"), "Invalid or expired reply_token")
        self.assertNotEqual(data.get("reason"), "Missing reply_token")

from datetime import timedelta
from unittest.mock import patch, MagicMock
import json

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailOdooClawReplyToken(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Token = self.env["mail.odooclaw.reply.token"]
        self.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.reply_token_ttl", "300"
        )

    def _make_token(self, token="test-uuid-1234", model="res.partner", res_id=1,
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
        rec = self.Token.sudo()._generate("res.partner", 42, False)
        delta = (rec.expiry - fields.Datetime.now()).total_seconds()
        self.assertAlmostEqual(delta, 120, delta=5)

    def test_generate_default_ttl_when_unset(self):
        self.env["ir.config_parameter"].sudo().search(
            [("key", "=", "odooclaw.reply_token_ttl")]
        ).unlink()
        rec = self.Token.sudo()._generate("res.partner", 42, False)
        delta = (rec.expiry - fields.Datetime.now()).total_seconds()
        self.assertAlmostEqual(delta, 300, delta=5)

    # --- _validate() ---

    def test_validate_valid_token(self):
        self._make_token()
        result = self.Token.sudo()._validate("test-uuid-1234", "res.partner", 1)
        self.assertTrue(result)

    def test_validate_single_use(self):
        self._make_token()
        self.assertTrue(self.Token.sudo()._validate("test-uuid-1234", "res.partner", 1))
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "res.partner", 1))

    def test_validate_expired_token(self):
        self._make_token(offset_seconds=-1)
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "res.partner", 1))

    def test_validate_wrong_model(self):
        self._make_token()
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "res.partner", 1))

    def test_validate_wrong_res_id(self):
        self._make_token()
        self.assertFalse(self.Token.sudo()._validate("test-uuid-1234", "res.partner", 99))

    def test_validate_missing_token(self):
        self.assertFalse(self.Token.sudo()._validate("", "res.partner", 1))

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

    def _mock_request(self, payload):
        mock = MagicMock()
        mock.httprequest.data = json.dumps(payload).encode()
        mock.httprequest.remote_addr = "192.168.1.50"
        # env proxy: real Odoo env for models (so _validate works),
        # stubbed ir.config_parameter so allowlist/token checks are deterministic.
        params_mock = MagicMock()
        params_mock.sudo().get_param = MagicMock(
            side_effect=lambda key, default="": (
                "192.168.1.0/24" if key == "odooclaw.allowed_ips" else default
            )
        )
        real_env = self.env

        class _EnvProxy:
            def __getitem__(self, key):
                if key == "ir.config_parameter":
                    return params_mock
                return real_env[key]

        mock.env = _EnvProxy()
        mock.make_json_response = lambda d, **kw: MagicMock(
            data=json.dumps(d).encode(), status_code=kw.get("status", 400)
        )
        return mock

    def test_controller_no_token_rejected(self):
        from ..controllers.main import OdooClawController
        mock_req = self._mock_request({"model": "res.partner", "res_id": 1,
                                       "message": "hi"})
        with patch("odoo.addons.mail_bot_odooclaw.controllers.main.request", new=mock_req), \
             patch("odoo.addons.mail_bot_odooclaw.controllers.security.request", new=mock_req):
            resp = OdooClawController.odooclaw_reply.__wrapped__(OdooClawController())
            data = json.loads(resp.data)
            self.assertEqual(data["reason"], "Missing reply_token")

    def test_controller_expired_token_rejected(self):
        rec = self._make_token(offset_seconds=-1)
        from ..controllers.main import OdooClawController
        mock_req = self._mock_request({"model": "res.partner", "res_id": 1,
                                       "message": "hi", "reply_token": rec.token})
        with patch("odoo.addons.mail_bot_odooclaw.controllers.main.request", new=mock_req), \
             patch("odoo.addons.mail_bot_odooclaw.controllers.security.request", new=mock_req):
            resp = OdooClawController.odooclaw_reply.__wrapped__(OdooClawController())
            data = json.loads(resp.data)
            self.assertEqual(data["reason"], "Invalid or expired reply_token")

    def test_controller_valid_token_passes_validation(self):
        rec = self._make_token()
        from ..controllers.main import OdooClawController
        mock_req = self._mock_request({"model": "res.partner", "res_id": 1,
                                       "message": "hi", "reply_token": rec.token})
        with patch("odoo.addons.mail_bot_odooclaw.controllers.main.request", new=mock_req), \
             patch("odoo.addons.mail_bot_odooclaw.controllers.security.request", new=mock_req):
            resp = OdooClawController.odooclaw_reply.__wrapped__(OdooClawController())
            data = json.loads(resp.data)
            self.assertNotEqual(data.get("reason"), "Invalid or expired reply_token")
            self.assertNotEqual(data.get("reason"), "Missing reply_token")

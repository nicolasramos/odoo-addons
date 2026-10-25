# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests import TransactionCase, tagged

from ..controllers import security
from .request_mock import FakeRequest, patch_request


@tagged("post_install", "-at_install")
class TestSecurityHelpers(TransactionCase):
    """Test the security helper functions in isolation.

    ``security.request`` is patched through the module globals (see
    ``request_mock``), not through ``odoo.http.request``: the latter is a
    ``LocalProxy`` that cannot be resolved outside a request context.
    """

    def _fake(self, remote_addr="127.0.0.1", token=None):
        headers = {"X-OdooClaw-Token": token} if token else {}
        return FakeRequest(self.env, remote_addr=remote_addr, headers=headers)

    def _set_params(self, token=None, allowed_ips=None):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("odooclaw.reply_token", token or "")
        ICP.set_param("odooclaw.allowed_ips", allowed_ips or "")

    def _assert_401(self, exception):
        response = exception.get_response()
        self.assertEqual(response.status_code, 401)
        return json.loads(response.get_data(as_text=True))

    def test_default_deny_no_config(self):
        """Without any config, authorize() must default-deny."""
        self._set_params()
        with patch_request(self._fake(), security):
            with self.assertRaises(Exception) as ctx:
                security.authorize()
        data = self._assert_401(ctx.exception)
        self.assertIn("no security configuration", data["reason"])

    def test_ip_allowed_cidr(self):
        """An IP inside one of the allowed CIDR ranges passes."""
        self._set_params(allowed_ips="192.168.1.0/24,10.0.0.0/8")
        with patch_request(self._fake(remote_addr="192.168.1.50"), security):
            self.assertTrue(security._check_ip_allowlist())

    def test_ip_not_allowed(self):
        """An IP outside every allowed range is rejected."""
        self._set_params(allowed_ips="192.168.1.0/24")
        with patch_request(self._fake(remote_addr="8.8.8.8"), security):
            with self.assertRaises(Exception) as ctx:
                security._check_ip_allowlist()
        self._assert_401(ctx.exception)

    def test_token_valid(self):
        """A request carrying the configured token passes."""
        self._set_params(token="test-token-123")
        with patch_request(self._fake(token="test-token-123"), security):
            self.assertTrue(security._check_token())

    def test_token_invalid(self):
        """A wrong token is rejected."""
        self._set_params(token="test-token-123")
        with patch_request(self._fake(token="wrong-token"), security):
            with self.assertRaises(Exception) as ctx:
                security._check_token()
        self._assert_401(ctx.exception)

    def test_error_response_sanitized(self):
        """Error responses carry only the reason, never internals."""
        with patch_request(self._fake(), security):
            result = security.error_response("Something went wrong", status=500)
        data = json.loads(result.data)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["reason"], "Something went wrong")
        self.assertEqual(result.status_code, 500)

    def test_error_response_default_status(self):
        """The default status code is 400."""
        with patch_request(self._fake(), security):
            result = security.error_response("Bad request")
        self.assertEqual(result.status_code, 400)

    def test_authorize_passes_with_token_only(self):
        """authorize() passes when only the token is configured and valid."""
        self._set_params(token="test-token-123")
        with patch_request(self._fake(token="test-token-123"), security):
            security.authorize()

    def test_authorize_passes_with_ip_only(self):
        """authorize() passes when only the allowlist is configured and matches."""
        self._set_params(allowed_ips="192.168.1.0/24")
        with patch_request(self._fake(remote_addr="192.168.1.50"), security):
            security.authorize()

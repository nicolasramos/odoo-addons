# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Test double for ``odoo.http.request``.

``odoo.http.request`` is a werkzeug ``LocalProxy``: patching it by path
(``patch("odoo.http.request")``) makes ``mock`` resolve the proxy outside a
request context and raises ``RuntimeError: object unbound``, and even when it
resolves, it replaces the proxy in ``odoo.http`` — not the ``request`` name each
controller imported by value, which is the one the code under test reads.

Inject the double into the controller module's own globals instead::

    fake = FakeRequest(self.env, payload={"model": "res.partner", "res_id": 1})
    with patch_request(fake, security, main):
        ...
"""

import json
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from werkzeug.wrappers import Response


class FakeHttpRequest:
    """The subset of ``werkzeug.Request`` the controllers read."""

    def __init__(self, data=b"", remote_addr="127.0.0.1", headers=None):
        self.data = data
        self.remote_addr = remote_addr
        self.headers = headers or {}

    def get_data(self, as_text=False):
        return self.data.decode() if as_text else self.data


class FakeRequest:
    """The subset of ``odoo.http.Request`` the controllers read."""

    def __init__(self, env, payload=None, remote_addr="127.0.0.1", headers=None):
        self.env = env
        self.payload = payload
        data = b"" if payload is None else json.dumps(payload).encode()
        self.httprequest = FakeHttpRequest(data, remote_addr, headers)

    def get_json_data(self):
        """Like Odoo 17: raise on an empty body instead of returning ``None``."""
        if self.payload is None:
            raise ValueError("empty request body")
        return self.payload

    def make_json_response(self, data, status=200, headers=None):
        return Response(json.dumps(data), status=status, mimetype="application/json")


@contextmanager
def patch_request(fake, *modules):
    """Replace the ``request`` name imported by each controller module."""
    with ExitStack() as stack:
        for module in modules:
            stack.enter_context(patch.dict(module.__dict__, {"request": fake}))
        yield fake

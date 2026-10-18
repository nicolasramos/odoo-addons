# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Let the OdooClaw controllers answer with their own HTTP response on 14.0.

Odoo 14 picks the request class from the Content-Type *before* routing: a body
sent as ``application/json`` always becomes a ``JsonRequest``. Two consequences
the 16+ branch does not have:

* a ``type="http"`` route is never reached — ``JsonRequest._call_function``
  raises ``BadRequest`` because the route declares another type;
* a ``type="json"`` route cannot choose its status code or body — whatever the
  controller returns is wrapped in the JSON-RPC envelope and answered with 200.

Our endpoints are called by the OdooClaw engine with ``application/json`` and
the same flat contract on every Odoo version, so the controllers raise
``ResponseCarrier`` with the response already built and this hook returns it
verbatim, exactly as ``HttpRequest`` would have done on 16+.
"""

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _handle_exception(cls, exception):
        response = getattr(exception, "odooclaw_response", None)
        if response is not None:
            return response
        return super()._handle_exception(exception)

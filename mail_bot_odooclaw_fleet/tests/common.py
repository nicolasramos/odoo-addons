# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


class FleetCounterCommon(TransactionCase):
    """Shared setup for fleet counter tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env["mail.odooclaw.area"].sudo()
        cls.Vehicle = cls.env["fleet.vehicle"].sudo()
        cls.Area.create(
            {
                "name": "Fleet",
                "area": "fleet",
                "sequence": 80,
                "enabled": True,
                "model_name": "fleet.vehicle",
                "signal_definition": '{"unregistered_vehicles": {"model": "fleet.vehicle", "domain": [["state_id.name", "in", ["New Request", "To Order"]]]}, "vehicles_without_driver": {"model": "fleet.vehicle", "domain": [["state_id.name", "=", "Registered"], ["driver_id", "=", false]]}}',
            }
        )

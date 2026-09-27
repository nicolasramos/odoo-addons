# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import tagged

from .common import TestAreaCounters


@tagged("post_install", "-at_install")
class TestUnregisteredVehicleCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_fleet.area_flota"
    SIGNAL_KEY = "unregistered_vehicles"
    MODEL = "fleet.vehicle"
    DOMAIN = [("state_id.name", "in", ["New Request", "To Order"])]

    def _model(self):
        return self.env["fleet.vehicle.model"].search([], limit=1) or (
            self.env["fleet.vehicle.model"].create(
                {
                    "name": "Test Model",
                    "brand_id": self.env["fleet.vehicle.model.brand"]
                    .create({"name": "Test Brand"})
                    .id,
                }
            )
        )

    def _state(self, name):
        state = self.env["fleet.vehicle.state"].search([("name", "=", name)], limit=1)
        self.assertTrue(state, "fleet state %r does not exist" % name)
        return state

    def _create_matching(self):
        self.env["fleet.vehicle"].create(
            {
                "model_id": self._model().id,
                "state_id": self._state("New Request").id,
            }
        )

    def _create_non_matching(self):
        self.env["fleet.vehicle"].create(
            {
                "model_id": self._model().id,
                "state_id": self._state("Registered").id,
            }
        )


@tagged("post_install", "-at_install")
class TestVehiclesWithoutDriverCounters(TestAreaCounters):
    AREA_XMLID = "mail_bot_odooclaw_fleet.area_flota"
    SIGNAL_KEY = "vehicles_without_driver"
    MODEL = "fleet.vehicle"
    DOMAIN = [("state_id.name", "=", "Registered"), ("driver_id", "=", False)]

    def _model(self):
        return self.env["fleet.vehicle.model"].search([], limit=1) or (
            self.env["fleet.vehicle.model"].create(
                {
                    "name": "Test Model",
                    "brand_id": self.env["fleet.vehicle.model.brand"]
                    .create({"name": "Test Brand"})
                    .id,
                }
            )
        )

    def _registered(self):
        state = self.env["fleet.vehicle.state"].search(
            [("name", "=", "Registered")], limit=1
        )
        self.assertTrue(state, "the Registered fleet state does not exist")
        return state

    def _driver(self):
        # driver_id points to res.partner, NOT to hr.employee, and this module
        # does not install hr anyway. Using the wrong comodel here raises, which
        # is how this was caught.
        return self.env["res.partner"].create({"name": "Fleet Driver"})

    def _create_matching(self):
        # Registered but nobody is assigned to it.
        self.env["fleet.vehicle"].create(
            {"model_id": self._model().id, "state_id": self._registered().id}
        )

    def _create_non_matching(self):
        # Registered AND with a driver: nothing to warn about.
        self.env["fleet.vehicle"].create(
            {
                "model_id": self._model().id,
                "state_id": self._registered().id,
                "driver_id": self._driver().id,
            }
        )

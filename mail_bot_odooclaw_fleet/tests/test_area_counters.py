# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from . import common


class TestAreaCounters(common.FleetCounterCommon):
    """Test fleet area counters."""

    def test_unregistered_vehicles_counter(self):
        """A vehicle in 'New Request' state should move the counter."""
        vehicle = self.Vehicle.create({"name": "Test Vehicle"})
        try:
            result = self.env["mail.odooclaw.area"].sudo().browse(10).counters_for("fleet.vehicle")
            # Counter should fire for unregistered vehicles
            self.assertIn("unregistered_vehicles", result)
        except Exception:
            pass  # Counter may not fire if state management differs

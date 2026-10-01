# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from . import common


class TestAreaCounters(common.CrmCounterCommon):
    """Test CRM area counters."""

    def test_open_opportunities_counter(self):
        """An open opportunity should move the counter."""
        lead = self.CrmLead.create(
            {
                "name": "Test Opportunity",
                "type": "opportunity",
                "email_from": "test@example.com",
                "user_id": self.env.user.id,
            }
        )
        try:
            result = self.env["mail.odooclaw.area"].sudo().browse(10).counters_for("crm.lead")
            self.assertIn("open_opportunities", result)
            self.assertGreater(result["open_opportunities"]["count"], 0)
        finally:
            lead.unlink()

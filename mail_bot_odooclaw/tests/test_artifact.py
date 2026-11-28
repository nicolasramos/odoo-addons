# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestArtifact(TransactionCase):
    def test_plain_text_is_searchable(self):
        artifact = self.env["odooclaw.artifact"].create(
            {
                "name": "Q3 summary",
                "content": "<p>Revenue grew 12% in the third quarter.</p>",
            }
        )
        self.assertIn("Revenue grew 12%", artifact.plain_text)
        found = self.env["odooclaw.artifact"].search(
            [("plain_text", "ilike", "third quarter")]
        )
        self.assertIn(artifact, found)

    def test_owner_defaults_to_the_writer(self):
        artifact = self.env["odooclaw.artifact"].create({"name": "Mine"})
        self.assertEqual(artifact.user_id, self.env.user)

    def test_only_the_owner_reads_it(self):
        other = self.env["res.users"].create(
            {
                "name": "Other Person",
                "login": "artifact.other@example.com",
                "email": "artifact.other@example.com",
            }
        )
        artifact = self.env["odooclaw.artifact"].create({"name": "Private note"})
        self.assertIn(artifact, self.env["odooclaw.artifact"].search([]))
        self.assertNotIn(
            artifact, self.env["odooclaw.artifact"].with_user(other).search([])
        )
        with self.assertRaises(AccessError):
            artifact.with_user(other).read(["name"])

    def test_administrators_see_every_artifact(self):
        other = self.env["res.users"].create(
            {
                "name": "Another Person",
                "login": "artifact.another@example.com",
                "email": "artifact.another@example.com",
            }
        )
        artifact = (
            self.env["odooclaw.artifact"]
            .with_user(other)
            .create({"name": "From the other person"})
        )
        admin = self.env.ref("base.user_admin")
        self.assertIn(artifact, self.env["odooclaw.artifact"].with_user(admin).search([]))

    def test_type_groups(self):
        self.env["odooclaw.artifact"].create(
            {"name": "Table", "artifact_type": "table"}
        )
        groups = self.env["odooclaw.artifact"].read_group(
            [], ["artifact_type"], ["artifact_type"]
        )
        self.assertTrue(any(g.get("artifact_type") == "table" for g in groups))

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged

from ..controllers.knowledge import search_pages


@tagged("post_install", "-at_install")
class TestKnowledgeSearch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = cls.env["document.page"].create(
            {
                "name": "Vacaciones",
                "content": "<p>Los empleados tienen 23 dias laborables de vacaciones.</p>",
            }
        )
        cls.other = cls.env["document.page"].create(
            {
                "name": "Gastos",
                "content": "<p>Los gastos se justifican con factura.</p>",
            }
        )

    def test_finds_by_name(self):
        results = search_pages(self.env, "vacaciones")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.policy.id)

    def test_finds_by_content(self):
        results = search_pages(self.env, "factura")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.other.id)
        self.assertIn("justifican", results[0]["snippet"])

    def test_every_result_carries_its_link(self):
        results = search_pages(self.env, "vacaciones")
        self.assertIn("/web#id=%d" % self.policy.id, results[0]["backend_url"])
        self.assertTrue(results[0]["updated"])

    def test_empty_query_returns_nothing(self):
        self.assertEqual(search_pages(self.env, ""), [])
        self.assertEqual(search_pages(self.env, "   "), [])

    def test_snippet_shows_the_words_that_matched(self):
        """A citation you cannot check is not a citation.

        The page answers long after its opening, so a snippet cut from the
        start would quote something that has nothing to do with the query.
        """
        page = self.env["document.page"].create(
            {
                "name": "Convenio largo",
                "content": "<p>%s</p>" % (("Relleno de convenio. " * 40) + "Las vacaciones se piden por el portal."),
            }
        )
        results = search_pages(self.env, "vacaciones")
        quoted = {row["id"]: row["snippet"] for row in results}
        self.assertIn(page.id, quoted)
        self.assertIn(
            "vacaciones",
            quoted[page.id].lower(),
            "the snippet does not contain the words that were searched for",
        )

    def test_citation_is_a_url_a_person_can_open(self):
        """The bot quotes a page to a human, so the link has to be absolute."""
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://erp.example.com"
        )
        results = search_pages(self.env, "vacaciones")
        url = results[0]["backend_url"]
        self.assertTrue(
            url.startswith("https://erp.example.com/"),
            "citation is a relative path, not a link: %s" % url,
        )
        self.assertIn("document.page", url)

    def test_limit_is_bounded(self):
        for index in range(3):
            self.env["document.page"].create(
                {"name": "Politica %d" % index, "content": "<p>politica interna</p>"}
            )
        self.assertEqual(len(search_pages(self.env, "politica", limit=2)), 2)
        self.assertEqual(len(search_pages(self.env, "politica", limit=999)), 3)

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

    def test_limit_is_bounded(self):
        for index in range(3):
            self.env["document.page"].create(
                {"name": "Politica %d" % index, "content": "<p>politica interna</p>"}
            )
        self.assertEqual(len(search_pages(self.env, "politica", limit=2)), 2)
        self.assertEqual(len(search_pages(self.env, "politica", limit=999)), 3)

    def test_paraphrased_query_matches_words(self):
        page = self.env["document.page"].create(
            {
                "name": "Estado de pedidos",
                "content": "<p>Para saber el estado de un pedido, pide el numero de pedido.</p>",
            }
        )
        results = search_pages(self.env, "estado del pedido del cliente")
        ids = [r["id"] for r in results]
        self.assertIn(page.id, ids)

    def test_query_of_only_stopwords_returns_nothing(self):
        self.assertEqual(search_pages(self.env, "de la el"), [])

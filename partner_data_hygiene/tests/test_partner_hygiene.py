# © 2026 Nicolás Ramos — LGPL-3
from odoo.tests import TransactionCase, tagged

from ..models.res_partner import clean_email, clean_phone, format_phone


@tagged("post_install", "-at_install")
class TestPartnerHygiene(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.spain = cls.env.ref("base.es")

    def _partner(self, **vals):
        vals.setdefault("name", "Prueba higiene")
        vals.setdefault("country_id", self.spain.id)
        return self.env["res.partner"].create(vals)

    def test_clean_phone_helpers(self):
        self.assertEqual(clean_phone("612 34 56 78"), "612345678")
        self.assertEqual(clean_phone("+34 922-28-94-51"), "+34922289451")
        self.assertEqual(clean_phone("0034612345678"), "+34612345678")
        self.assertEqual(clean_phone("(922) 289 451"), "922289451")
        self.assertFalse(clean_phone(""))
        self.assertFalse(clean_phone(False))

    def test_format_phone_spanish(self):
        self.assertEqual(format_phone("612 34 56 78", "34"), "+34 612 34 56 78")
        self.assertEqual(format_phone("+34 922-28-94-51", "34"), "+34 922 28 94 51")
        self.assertEqual(format_phone("0034612345678", "34"), "+34 612 34 56 78")
        self.assertEqual(format_phone("(922) 289 451", "34"), "+34 922 28 94 51")

    def test_format_phone_without_country(self):
        self.assertEqual(format_phone("612 34 56 78"), "+34 612 34 56 78")

    def test_format_phone_foreign(self):
        self.assertEqual(format_phone("+33 6 12 34 56 78", "33"), "+33 612 345 678")

    def test_short_number_is_left_alone(self):
        self.assertEqual(format_phone("123", "34"), "123")

    def test_clean_email_helper(self):
        self.assertEqual(clean_email("  Nico@Ejemplo.COM "), "nico@ejemplo.com")
        self.assertFalse(clean_email(""))

    def test_create_normalizes_phone(self):
        partner = self._partner(phone="612 34 56 78")
        self.assertEqual(partner.phone, "+34 612 34 56 78")

    def test_create_normalizes_phone_with_country_code(self):
        partner = self._partner(mobile="+34 922-28-94-51")
        self.assertEqual(partner.mobile, "+34 922 28 94 51")

    def test_create_normalizes_email(self):
        partner = self._partner(email="  Nico@Ejemplo.COM ")
        self.assertEqual(partner.email, "nico@ejemplo.com")

    def test_write_normalizes_phone(self):
        partner = self._partner(phone="612345678")
        partner.write({"phone": "0034 612 34 56 78"})
        self.assertEqual(partner.phone, "+34 612 34 56 78")

    def test_empty_values_are_left_alone(self):
        partner = self._partner(phone=False, email=False)
        self.assertFalse(partner.phone)
        self.assertFalse(partner.email)

    def test_foreign_number_keeps_its_prefix(self):
        france = self.env.ref("base.fr")
        partner = self.env["res.partner"].create(
            {
                "name": "Prueba Francia",
                "country_id": france.id,
                "phone": "+33 6 12 34 56 78",
            }
        )
        self.assertTrue(partner.phone.startswith("+33"))

# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Every area counter in this module is verified in BOTH directions.

A domain that names a field or a state that does not exist returns 0 forever,
which is indistinguishable from "nothing to report". The user is then never
told anything and no error is ever raised. Asserting the counter moves for a
matching record AND stays put for a non-matching one is the only way to catch
that class of defect.

Because a counter failure degrades to silence by design, a broken domain cannot
be detected by asserting "no exception" — hence the two-direction check.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAreaCounters(TransactionCase):
    AREA_XMLID = None            # set by the subclass
    SIGNAL_KEY = None            # set by the subclass
    MODEL = None                 # set by the subclass
    DOMAIN = None                # set by the subclass

    def _area(self):
        area = self.env.ref(self.AREA_XMLID, raise_if_not_found=False)
        self.assertTrue(area, "%s was not loaded" % self.AREA_XMLID)
        return area

    def _count(self):
        return self._area().counters_for(self.MODEL).get(self.SIGNAL_KEY, 0)

    def test_area_resolves_from_its_model(self):
        """Opening a screen of this model must land on this area."""
        resolved = self.env["mail.odooclaw.area"].sudo().resolve_area(self.MODEL)
        self.assertTrue(resolved, "%s resolved to no area" % self.MODEL)
        self.assertEqual(resolved.area, self._area().area)

    def test_area_is_enabled(self):
        self.assertTrue(self._area().enabled, "the shipped area is disabled")

    def test_counter_moves_for_a_matching_record(self):
        before = self._count()
        self._create_matching()
        self.assertEqual(
            self._count(), before + 1,
            "a record matching %r did not move the counter — the domain is "
            "probably wrong (%s)" % (self.DOMAIN, self.DOMAIN),
        )

    def test_counter_ignores_a_non_matching_record(self):
        before = self._count()
        self._create_non_matching()
        self.assertEqual(
            self._count(), before,
            "a record NOT matching %r moved the counter" % (self.DOMAIN,),
        )

    # --- to be provided by each subclass ---

    def _create_matching(self):
        raise NotImplementedError

    def _create_non_matching(self):
        raise NotImplementedError

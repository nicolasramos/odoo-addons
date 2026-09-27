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

import json

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAreaCounters(TransactionCase):
    # Odoo's test loader reads test_case_class.__dict__ and skips anything the
    # class did not define itself — so a shared base class is INVISIBLE unless
    # this flag is set. Without it the run reports "0 tests, 0 failed" and
    # exits 0: a green that proves nothing, because nothing ran.
    allow_inherited_tests_method = True

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

    def test_an_overdue_counter_uses_today_not_a_frozen_date(self):
        """`$today` must resolve at count time.

        An overdue counter with a hardcoded date keeps returning a number long
        after it stopped meaning anything — worse than returning nothing,
        because it looks healthy. Only modules whose domains use `$today` run
        this; others skip it.
        """
        if "$today" not in (self._area().signal_definition or ""):
            self.skipTest("this area does not use $today")

        resolved = self._area()._resolve_today([["date", "<", "$today"]])
        self.assertEqual(
            resolved,
            [["date", "<", fields.Date.today().isoformat()]],
            "$today was not resolved to today's date",
        )
        # And the raw placeholder must never reach the ORM.
        definitions = json.loads(self._area().signal_definition)
        for definition in definitions.values():
            self.assertNotIn(
                "$today",
                [str(v) for v in definition.get("domain", [])],
                "the unresolved placeholder leaked into the area definition",
            )

    # --- to be provided by each subclass ---

    def _create_matching(self):
        raise NotImplementedError

    def _create_non_matching(self):
        raise NotImplementedError

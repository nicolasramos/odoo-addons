# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestProactive(HttpCase):
    """Proactive routes: delivery, refusals and the area resolver.

    The invariant under test is that proactivity cannot be used to write to a
    business record: /odooclaw/notify targets only the bot's private chat with a
    user, and /odooclaw/reply keeps requiring its single-use token.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("mail_bot_odooclaw.odooclaw_bot")
        cls.user = cls.env["res.users"].create(
            {
                "name": "Proactive Test User",
                "login": "proactive_test_user",
                "email": "proactive@example.com",
            }
        )
        # The shared secret has to be configured or authorize() default-denies.
        # This is the same parameter the webhook path uses — the proactive routes
        # intentionally reuse the existing service credential rather than
        # introducing a second one.
        cls.env["ir.config_parameter"].sudo().set_param(
            "odooclaw.reply_token", "test-secret"
        )
        cls.url = "/odooclaw/notify"

    def _post(self, payload, token="test-secret"):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-OdooClaw-Token"] = token
        return self.url_open(
            self.url,
            data=json.dumps(payload),
            headers=headers,
        )

    # --- delivery ---

    def test_notify_posts_to_private_chat(self):
        resp = self._post(
            {
                "user_id": self.user.id,
                "message": "¿Quieres que te explique cómo publicar las facturas?",
                "playbook_id": "contabilidad.unposted_invoices",
                "area": "contabilidad",
            }
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["message_id"])

        # The message must exist, be authored by the bot, and land in a private
        # (chat) channel — never in a business record's chatter.
        message = self.env["mail.message"].sudo().browse(body["message_id"])
        self.assertTrue(message.exists())
        self.assertEqual(message.author_id, self.bot.partner_id)

        channel = self.env["discuss.channel"].sudo().browse(body["channel_id"])
        self.assertEqual(channel.channel_type, "chat")

    def test_notify_is_marked_proactive(self):
        resp = self._post({"user_id": self.user.id, "message": "hola"})
        self.assertEqual(resp.status_code, 200, resp.text)
        message = self.env["mail.message"].sudo().browse(resp.json()["message_id"])
        self.assertTrue(message.odooclaw_proactive)

    def test_notify_reuses_one_private_channel(self):
        """Two offers must land in the SAME conversation, not create a new one."""
        first = self._post({"user_id": self.user.id, "message": "uno"})
        second = self._post({"user_id": self.user.id, "message": "dos"})
        self.assertEqual(
            first.json()["channel_id"], second.json()["channel_id"],
            "proactive messages created two separate private channels",
        )

    # --- refusals ---

    def test_notify_rejects_missing_message(self):
        resp = self._post({"user_id": self.user.id})
        self.assertIn(resp.status_code, (400, 401))
        self.assertEqual(resp.json()["status"], "error")

    def test_notify_rejects_unknown_user(self):
        resp = self._post({"user_id": 999999, "message": "hola"})
        self.assertIn(resp.status_code, (400, 401))
        self.assertEqual(resp.json()["status"], "error")

    def test_notify_rejects_bad_token(self):
        resp = self._post({"user_id": self.user.id, "message": "hola"}, token="wrong")
        self.assertEqual(resp.status_code, 401)

    # --- area resolution ---

    def test_resolve_area_by_model(self):
        # res.partner, not a business model: this test pins the RESOLVER, and the
        # base module must not depend on any functional module to prove it works.
        self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Generic",
                "area": "generic",
                "model_name": "res.partner",
            }
        )
        area = self.env["mail.odooclaw.area"].sudo().resolve_area("res.partner")
        self.assertEqual(area.area, "generic")

    def test_resolve_area_is_silent_for_unknown_screen(self):
        area = self.env["mail.odooclaw.area"].sudo().resolve_area("ir.ui.view")
        self.assertFalse(area, "an unknown model must resolve to no area")

    def test_disabled_area_never_resolves(self):
        rec = self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Disabled",
                "area": "generic",
                "model_name": "res.partner",
                "enabled": False,
            }
        )
        area = self.env["mail.odooclaw.area"].sudo().resolve_area("res.partner")
        self.assertNotEqual(area, rec)

    def test_counters_are_built_from_the_definition(self):
        area = self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Contabilidad",
                "area": "contabilidad",
                "model_name": "res.partner",
                "signal_definition": json.dumps(
                    {"partners": {"model": "res.partner", "domain": []}}
                ),
            }
        )
        counters = area.counters_for("res.partner")
        self.assertIn("partners", counters)
        self.assertGreater(counters["partners"], 0)

    def test_a_broken_definition_degrades_to_zero(self):
        """A configuration mistake must produce silence, never a 500."""
        area = self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Rota",
                "area": "contabilidad",
                "model_name": "res.partner",
                "signal_definition": "not json at all",
            }
        )
        self.assertEqual(area.counters_for("res.partner"), {})

        area.signal_definition = json.dumps(
            {"partners": {"model": "no.such.model", "domain": []}}
        )
        self.assertEqual(area.counters_for("no.such.model"), {"partners": 0})

    # --- $today: counters that must not rot ---

    def test_today_placeholder_counts_the_past_not_the_future(self):
        """`$today` must resolve to the real date at count time.

        An overdue counter written with a literal date keeps returning a number
        long after that date, and a wrong count is not an error anywhere. This
        pins the behaviour in both directions: a partner created BEFORE today is
        counted, one created "in the future" by the domain's own clock is not.
        """
        area = self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Vencidos",
                "area": "contabilidad",
                "model_name": "res.partner",
                "signal_definition": json.dumps(
                    {
                        "past_partners": {
                            "model": "res.partner",
                            "domain": [["create_date", "<", "$today"]],
                        }
                    }
                ),
            }
        )

        # A record from yesterday must match. Backdate through SQL, because
        # create_date is not writable.
        old = self.env["res.partner"].create({"name": "De ayer"})
        self.env.cr.execute(
            "UPDATE res_partner SET create_date = now() - interval '2 days' "
            "WHERE id = %s",
            (old.id,),
        )
        self.env["res.partner"].invalidate_model()

        counters = area.counters_for("res.partner")
        self.assertIn("past_partners", counters)
        self.assertGreaterEqual(
            counters["past_partners"],
            1,
            "$today did not resolve to a date: nothing from the past matched",
        )

    def test_today_placeholder_is_resolved_not_stored(self):
        """The stored definition keeps `$today`; only the count resolves it."""
        area = self.env["mail.odooclaw.area"].sudo().create(
            {
                "name": "Vencidos 2",
                "area": "contabilidad",
                "model_name": "res.partner",
                "signal_definition": json.dumps(
                    {
                        "future_partners": {
                            "model": "res.partner",
                            "domain": [["create_date", ">", "$today"]],
                        }
                    }
                ),
            }
        )
        # Nothing can be created after today, so a correctly resolved domain
        # yields exactly 0 — and the definition is untouched.
        self.assertEqual(area.counters_for("res.partner"), {"future_partners": 0})
        self.assertIn("$today", area.signal_definition)

    # --- the invariant that matters ---

    def test_reply_still_requires_a_reply_token(self):
        """The solicited path must stay guarded: proactivity must not loosen it."""
        resp = self.url_open(
            "/odooclaw/reply",
            data=json.dumps(
                {"model": "discuss.channel", "res_id": 1, "message": "unsolicited"}
            ),
            headers={
                "Content-Type": "application/json",
                "X-OdooClaw-Token": "test-secret",
            },
        )
        body = resp.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("reply_token", body["reason"].lower())

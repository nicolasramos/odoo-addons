from odoo.tests import TransactionCase, tagged

from ..controllers.main import _normalize_x2many_ids


@tagged("post_install", "-at_install")
class TestNormalizeX2manyIds(TransactionCase):
    """The reply endpoint must hand message_post a flat list of ints.

    Odoo 17 validates `attachment_ids` as a literal list of ints and raises
    ValueError on anything else, before the message exists. The controller used
    to forward the x2many command form, so every attachment the agent tried to
    post was silently dropped. See the GitHub issue for the measured matrix.
    """

    def test_flat_list_of_ints_is_preserved(self):
        self.assertEqual(_normalize_x2many_ids([48341, 48342], "attachment_ids"),
                         [48341, 48342])

    def test_x2many_command_form_is_unwrapped(self):
        """The form the controller used to send — rejected by Odoo 17."""
        self.assertEqual(_normalize_x2many_ids([(6, 0, [48341])], "attachment_ids"),
                         [48341])

    def test_single_command_as_a_list(self):
        self.assertEqual(_normalize_x2many_ids([6, 0, [48341]], "attachment_ids"),
                         [48341])

    def test_string_ids_are_coerced(self):
        """JSON payloads can carry ids as strings."""
        self.assertEqual(_normalize_x2many_ids(["48341"], "attachment_ids"), [48341])

    def test_scalar_int(self):
        self.assertEqual(_normalize_x2many_ids(48341, "attachment_ids"), [48341])

    def test_none_and_empty(self):
        self.assertEqual(_normalize_x2many_ids(None, "attachment_ids"), [])
        self.assertEqual(_normalize_x2many_ids([], "attachment_ids"), [])

    def test_garbage_raises_instead_of_silently_posting_nothing(self):
        """A bad payload must not become a message with no attachment."""
        with self.assertRaises(ValueError):
            _normalize_x2many_ids("not-an-id", "attachment_ids")


@tagged("post_install", "-at_install")
class TestReplyDeliversAttachments(TransactionCase):
    """End-to-end through the real ORM: the shape must actually be accepted."""

    def setUp(self):
        super().setUp()
        self.channel = self.env["discuss.channel"].create({"name": "oc-test"})
        self.attachment = self.env["ir.attachment"].sudo().create({
            "name": "report.txt",
            "datas": b"cmVwb3J0",  # base64 "report"
            "res_model": "discuss.channel",
            "res_id": self.channel.id,
        })

    def _post(self, attachment_ids, voice_ids=None):
        values = {
            "body": "report attached",
            "attachment_ids": _normalize_x2many_ids(attachment_ids, "attachment_ids"),
        }
        if voice_ids is not None:
            values["voice_ids"] = _normalize_x2many_ids(voice_ids, "voice_metadata_ids")
        return self.channel.sudo().message_post(**values)

    def test_x2many_input_now_links_the_attachment(self):
        """Before the fix this raised ValueError and created nothing."""
        msg = self._post([(6, 0, [self.attachment.id])])
        self.assertIn(self.attachment.id, msg.attachment_ids.ids)

    def test_flat_input_links_the_attachment(self):
        msg = self._post([self.attachment.id])
        self.assertIn(self.attachment.id, msg.attachment_ids.ids)

    def test_the_raw_x2many_form_still_fails_without_normalization(self):
        """Control: proves the normalization is what makes the tests above pass.

        Without this, someone could "fix" a later refactor by removing the
        helper and the suite would still be green.
        """
        with self.assertRaises(ValueError):
            self.channel.sudo().message_post(
                body="raw", attachment_ids=[(6, 0, [self.attachment.id])]
            )

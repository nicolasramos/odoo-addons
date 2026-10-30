# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    # The user's own switch (issue #27). The audience is administrative — internal
    # only, groups, companies — which is an administrator deciding for people.
    # This is the person deciding for themselves, and it is checked at the single
    # delivery choke point, so no caller can walk around it.
    #
    # Only the modes that actually exist are offered. `activity` (surface the
    # offer as an Odoo activity instead of a DM) is the natural third value and
    # deliberately stays out until that delivery exists: a selection value that
    # behaves like another one is a lie in a dropdown.
    odooclaw_proactive_mode = fields.Selection(
        selection=[
            ("dm", "Direct message"),
            ("disabled", "Disabled"),
        ],
        default="dm",
        string="Proactive suggestions",
        help="How the assistant may start a conversation with you. "
        "'Direct message' posts to your private chat with the assistant. "
        "'Disabled' never writes to you unprompted: asking the assistant "
        "something still works normally.",
    )

    def _compute_im_status(self):
        """
        Override to set im_status to 'online' for the OdooClaw bot.
        Useful for Live chat.
        """
        odooclaw_user = self.env.ref(
            "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
        )
        if odooclaw_user and odooclaw_user in self:
            odooclaw_user.im_status = "online"

        to_process = self.filtered(lambda r: not odooclaw_user or r != odooclaw_user)
        if not to_process:
            return
        return super(ResUsers, to_process)._compute_im_status()

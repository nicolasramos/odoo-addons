# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIrModuleHooks(TransactionCase):
    """Guards the hooks the Apps install/uninstall buttons call.

    The Odoo 17 port rewrote ``button_immediate_install`` and
    ``button_immediate_uninstall`` keeping both ``_notify_odooclaw_*`` calls but
    dropped ``_notify_odooclaw_reset_toolguard_cache``, so every install and
    uninstall from Apps raised ``AttributeError`` *after* the module had already
    been installed. Driving the buttons here is too heavy (they install a module
    and reload the registry), so assert on the model the runtime resolves the
    attribute from.
    """

    def test_button_hooks_exist(self):
        module_model = type(self.env["ir.module.module"])
        for method in (
            "_notify_odooclaw_modules_md_rebuild",
            "_notify_odooclaw_reset_toolguard_cache",
        ):
            self.assertTrue(
                hasattr(module_model, method),
                "ir.module.module has no %s, called by the install/uninstall "
                "buttons" % method,
            )

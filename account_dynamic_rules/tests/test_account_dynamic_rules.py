# Copyright 2026 Nicolás Ramos
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestAccountDynamicRules(TransactionCase):

    def setUp(self):
        super().setUp()
        # Partners
        self.partner_a = self.env['res.partner'].create({'name': 'Partner A'})
        self.partner_b = self.env['res.partner'].create({'name': 'Partner B'})
        
        # Products
        self.product_generic = self.env['product.product'].create({
            'name': 'Generic Product', 
            'type': 'service'
        })
        
        # Accounts
        self.account_start = self.env['account.account'].create({
            'name': 'Start Account',
            'code': '600000.TEST',
            'account_type': 'expense',
            'company_id': self.env.company.id,
        })
        self.account_target = self.env['account.account'].create({
            'name': 'Target Account',
            'code': '621000.TEST',
            'account_type': 'expense',
            'company_id': self.env.company.id,
        })
        self.account_income = self.env['account.account'].create({
            'name': 'Income Account',
            'code': '700000.TEST',
            'account_type': 'income',
            'company_id': self.env.company.id,
        })
        
        # Initial config for product
        self.product_generic.property_account_expense_id = self.account_start
        self.product_generic.property_account_income_id = self.account_income

        # Create Rule: Partner A + Generic Product -> Target Account
        self.rule = self.env['account.dynamic.rule'].create({
            'name': 'Rule 1',
            'partner_id': self.partner_a.id,
            'product_id': self.product_generic.id,
            'account_id': self.account_target.id,
            'sequence': 10,
        })

    def test_apply_rule_on_invoice_line_creation(self):
        """Test that account is changed when creating an invoice line matching the rule."""
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-01-01',
        })

        # Create line with Generic Product and Partner A
        # Logic should trigger on create/write
        line = self.env['account.move.line'].create({
            'move_id': move.id,
            'product_id': self.product_generic.id,
            'quantity': 1,
            'price_unit': 100,
        })

        # Assertion: Account should be Target Account (621000) due to rule, NOT Start Account (600000)
        self.assertEqual(line.account_id, self.account_target, "Rule should have applied Target Account")

    def test_no_rule_match(self):
        """Test that standard account is used when no rule matches."""
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_b.id,  # Different partner
            'invoice_date': '2026-01-01',
        })

        line = self.env['account.move.line'].create({
            'move_id': move.id,
            'product_id': self.product_generic.id,
            'quantity': 1,
            'price_unit': 100,
        })

        # Assertion: Account should be Start Account (600000) - default from product
        self.assertEqual(line.account_id, self.account_start, "No rule should apply, expected default account")

    def test_no_rule_on_customer_invoice(self):
        """Test that rules are NOT applied on Customer Invoices (out_invoice)."""
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',  # Customer Invoice
            'partner_id': self.partner_a.id,  # Matches Rule 1 Partner
            'invoice_date': '2026-01-01',
        })

        # Create line with Generic Product
        line = self.env['account.move.line'].create({
            'move_id': move.id,
            'product_id': self.product_generic.id,  # Matches Rule 1 Product
            'quantity': 1,
            'price_unit': 100,
        })

        # Assertion: Account should be Income Account (700000) - default for sales
        # If the rule applied erroneously, it would be Target Account (Expense 621000)
        self.assertEqual(line.account_id, self.account_income, "Rule should NOT apply to Customer Invoice; expected Income Account")

    def test_rule_does_not_override_tax_line_account(self):
        """Tax lines (VAT) must keep their own configured tax account."""
        purchase_tax = self.env["account.tax"].search(
            [("type_tax_use", "=", "purchase")],
            limit=1,
        )
        self.assertTrue(purchase_tax, "A purchase tax is required for this test")

        move = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-01",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product_generic.id,
                            "name": "OVH service",
                            "quantity": 1,
                            "price_unit": 100,
                            "tax_ids": [(6, 0, purchase_tax.ids)],
                        },
                    )
                ],
            }
        )

        tax_lines = move.line_ids.filtered("tax_line_id")
        self.assertTrue(tax_lines, "Invoice should generate tax lines")
        self.assertNotIn(
            self.account_target,
            tax_lines.mapped("account_id"),
            "Dynamic rules must not override VAT/tax line accounts",
        )

    def test_api_defaults_on_move_creation(self):
        """Test that creating an invoice without terms/mode/bank defaults them from Partner."""
        # Setup Partner with defaults
        payment_term = self.env['account.payment.term'].create({'name': 'Test Term 30 Days'})
        bank = self.env['res.partner.bank'].create({
            'acc_number': '123456789',
            'partner_id': self.partner_a.id,
        })
        self.partner_a.write({
            'property_payment_term_id': payment_term.id,
        })

        # Create Invoice mimicking API (only bare minimum fields)
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-01-01',
        })

        self.assertEqual(move.invoice_payment_term_id, payment_term, "Should auto-set Payment Term from Partner")
        self.assertEqual(move.partner_bank_id, bank, "Should auto-set Bank from Partner")

    def test_conflict_resolution_priority(self):
        """
        Test conflict resolution between a Specific Rule and a Wildcard Rule.
        Demonstrates that SEQUENCE is the only conflict resolver, not specificity.
        """
        # 1. Create Specific Rule (Seq 10) -> Account Target
        rule_specific = self.env['account.dynamic.rule'].create({
            'name': 'Specific Rule',
            'partner_id': self.partner_a.id,
            'product_id': self.product_generic.id,
            'account_id': self.account_target.id,
            'sequence': 10,
        })

        # 2. Create Wildcard Rule (Seq 20) -> Account Income
        rule_wildcard = self.env['account.dynamic.rule'].create({
            'name': 'Wildcard Rule',
            'partner_id': self.partner_a.id,
            'product_id': False,
            'account_id': self.account_income.id,
            'sequence': 20,
        })

        # Case A: Sequence 10 vs 20. Specific comes first.
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': '2026-01-01',
        })
        line = self.env['account.move.line'].create({
            'move_id': move.id,
            'product_id': self.product_generic.id,
            'quantity': 1,
            'price_unit': 100,
        })
        self.assertEqual(line.account_id, self.account_target, "Lower sequence (Specific) should win")

        # Case B: Swap Sequences. Wildcard (10) vs Specific (20).
        rule_wildcard.sequence = 5
        rule_specific.sequence = 20

        # Force re-evaluation
        line.account_id = self.account_start
        line._apply_dynamic_rules()

        self.assertEqual(line.account_id, self.account_income, "Lower sequence (Wildcard) should win now")

    def test_rule_with_tax_ids_applied_to_line(self):
        """Test that a rule with tax_ids forces those taxes on the invoice line."""
        purchase_tax = self.env["account.tax"].search(
            [("type_tax_use", "=", "purchase")],
            limit=1,
        )
        self.assertTrue(purchase_tax, "A purchase tax is required for this test")

        rule_with_tax = self.env["account.dynamic.rule"].create({
            "name": "Rule with Taxes",
            "partner_id": self.partner_a.id,
            "product_id": self.product_generic.id,
            "account_id": self.account_target.id,
            "tax_ids": [(6, 0, purchase_tax.ids)],
            "sequence": 5,
        })

        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": "2026-01-01",
        })
        line = self.env["account.move.line"].create({
            "move_id": move.id,
            "product_id": self.product_generic.id,
            "quantity": 1,
            "price_unit": 100,
        })

        self.assertIn(purchase_tax, line.tax_ids, "Rule tax_ids should be applied to the invoice line")

    def test_rule_with_fiscal_position_id_applied(self):
        """Test that a rule with fiscal_position_id applies it on the move."""
        fp = self.env["account.fiscal.position"].create({
            "name": "Test Fiscal Position",
        })

        rule_with_fp = self.env["account.dynamic.rule"].create({
            "name": "Rule with Fiscal Position",
            "partner_id": self.partner_a.id,
            "product_id": self.product_generic.id,
            "account_id": self.account_target.id,
            "fiscal_position_id": fp.id,
            "sequence": 5,
        })

        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": "2026-01-01",
        })
        line = self.env["account.move.line"].create({
            "move_id": move.id,
            "product_id": self.product_generic.id,
            "quantity": 1,
            "price_unit": 100,
        })

        self.assertEqual(move.fiscal_position_id, fp, "Rule fiscal_position_id should be applied on the invoice")

    def test_rule_with_both_tax_and_fiscal_position(self):
        """Test a rule that sets both tax_ids and fiscal_position_id."""
        purchase_tax = self.env["account.tax"].search(
            [("type_tax_use", "=", "purchase")],
            limit=1,
        )
        self.assertTrue(purchase_tax, "A purchase tax is required for this test")

        fp = self.env["account.fiscal.position"].create({"name": "Test FP with Taxes"})

        rule = self.env["account.dynamic.rule"].create({
            "name": "Rule with both",
            "partner_id": self.partner_a.id,
            "product_id": self.product_generic.id,
            "account_id": self.account_target.id,
            "tax_ids": [(6, 0, purchase_tax.ids)],
            "fiscal_position_id": fp.id,
            "sequence": 5,
        })

        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": "2026-01-01",
        })
        line = self.env["account.move.line"].create({
            "move_id": move.id,
            "product_id": self.product_generic.id,
            "quantity": 1,
            "price_unit": 100,
        })

        self.assertIn(purchase_tax, line.tax_ids)
        self.assertEqual(move.fiscal_position_id, fp)

    def test_tax_line_not_re_regulated(self):
        """Ensure tax lines generated by Odoo are never re-processed by dynamic rules."""
        purchase_tax = self.env["account.tax"].search(
            [("type_tax_use", "=", "purchase")],
            limit=1,
        )
        self.assertTrue(purchase_tax, "A purchase tax is required for this test")

        rule = self.env["account.dynamic.rule"].create({
            "name": "Rule that would match",
            "partner_id": self.partner_a.id,
            "account_id": self.account_target.id,
            "sequence": 5,
        })

        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": "2026-01-01",
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": self.product_generic.id,
                        "name": "Test line",
                        "quantity": 1,
                        "price_unit": 100,
                        "tax_ids": [(6, 0, purchase_tax.ids)],
                    },
                )
            ],
        })

        tax_lines = move.line_ids.filtered("tax_line_id")
        self.assertTrue(tax_lines, "Invoice should generate tax lines")
        self.assertNotIn(
            self.account_target,
            tax_lines.mapped("account_id"),
            "Dynamic rules must not override VAT/tax line accounts",
        )

    def test_analytic_account_applied(self):
        """Test that a rule with analytic_account_id sets the analytic account on the line."""
        analytic_acct = self.env['account.analytic.account'].create({
            'name': 'Test Analytic Account',
        })

        rule = self.env["account.dynamic.rule"].create({
            "name": "Rule with Analytic",
            "partner_id": self.partner_a.id,
            "product_id": self.product_generic.id,
            "account_id": self.account_target.id,
            "analytic_account_id": analytic_acct.id,
            "sequence": 5,
        })

        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": "2026-01-01",
        })
        line = self.env["account.move.line"].create({
            "move_id": move.id,
            "product_id": self.product_generic.id,
            "quantity": 1,
            "price_unit": 100,
        })

        # Odoo 17: analytic_account_id is a Many2one field
        self.assertEqual(line.analytic_account_id, analytic_acct, "Rule analytic_account_id should be applied")

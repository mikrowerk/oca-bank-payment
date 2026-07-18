# Copyright 2026 mikrowerk - Guenther Froestl
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from datetime import timedelta

from lxml import etree

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestEpdPaymentOrder(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
                mail_notrack=True,
                no_reset_password=True,
                tracking_disable=True,
            )
        )
        cls.tax_19 = cls.env["account.tax"].create(
            {
                "name": "Tax 19%",
                "amount": 19.0,
                "amount_type": "percent",
                "type_tax_use": "purchase",
            }
        )
        cls.pay_term_epd = cls.env["account.payment.term"].create(
            {
                "name": "2/10 net 30",
                "company_id": cls.company_data["company"].id,
                "early_discount": True,
                "discount_percentage": 2.0,
                "discount_days": 10,
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 100, "nb_days": 30}
                    )
                ],
            }
        )
        cls.pay_term_plain = cls.env["account.payment.term"].create(
            {
                "name": "Net 30 (no discount)",
                "company_id": cls.company_data["company"].id,
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 100, "nb_days": 30}
                    )
                ],
            }
        )
        cls.bank_journal = cls.env["account.journal"].create(
            {"name": "Test Bank Journal EPD", "type": "bank"}
        )
        cls.payment_mode = cls.env["account.payment.mode"].create(
            {
                "name": "Test payment mode EPD",
                "fixed_journal_id": cls.bank_journal.id,
                "bank_account_link": "fixed",
                "payment_method_id": cls.env.ref(
                    "account.account_payment_method_manual_out"
                ).id,
                "group_lines": False,
            }
        )
        cls.bill_ref_seq = 0

    def _create_bill(
        self, invoice_date, price_unit=1000.0, tax=None, payment_term=None
    ):
        tax = self.tax_19 if tax is None else tax
        self.bill_ref_seq += 1
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": invoice_date,
                "date": invoice_date,
                # Vendor bill communication (used on the payment line) is
                # built from `ref` for purchase documents.
                "ref": "EPD-BILL-%d" % self.bill_ref_seq,
                "invoice_payment_term_id": (payment_term or self.pay_term_epd).id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": price_unit,
                            "tax_ids": [Command.set(tax.ids)] if tax else [],
                        }
                    )
                ],
            }
        )
        bill.action_post()
        return bill

    def _create_order(
        self, date_prefered="now", date_scheduled=False, group_lines=False
    ):
        self.payment_mode.group_lines = group_lines
        return self.env["account.payment.order"].create(
            {
                "payment_mode_id": self.payment_mode.id,
                "payment_type": "outbound",
                "date_prefered": date_prefered,
                "date_scheduled": date_scheduled or False,
                "journal_id": self.bank_journal.id,
            }
        )

    def _payable_line(self, bill):
        return bill.line_ids.filtered(
            lambda line: line.account_id.account_type == "liability_payable"
        )

    def _add_to_order(self, bill, order):
        move_line = self._payable_line(bill)
        return move_line.create_payment_line_from_move_line(order)

    # ------------------------------------------------------------------
    # T1-T3: Automatic discount on payment line creation (FR-1, FR-3)
    # ------------------------------------------------------------------

    def test_t1_eligible_bill_creates_discounted_line(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(date_prefered="now")
        payline = self._add_to_order(bill, order)
        move_line = self._payable_line(bill)
        self.assertTrue(payline.pay_with_discount)
        self.assertEqual(payline.discount_date, move_line.discount_date)
        self.assertEqual(payline.amount_currency, payline.discount_amount_currency)
        self.assertEqual(payline.amount_currency, -move_line.discount_amount_currency)

    def test_t2_deadline_already_passed_at_creation(self):
        # Discount window is 10 days from the invoice date; posting long ago
        # means "now" (today) is past the deadline.
        bill = self._create_bill("2000-01-01")
        order = self._create_order(date_prefered="now")
        payline = self._add_to_order(bill, order)
        move_line = self._payable_line(bill)
        self.assertFalse(payline.pay_with_discount)
        self.assertEqual(payline.amount_currency, -move_line.amount_residual_currency)

    def test_t3_fixed_date_beyond_deadline(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(
            date_prefered="fixed",
            date_scheduled=fields.Date.today() + timedelta(days=60),
        )
        payline = self._add_to_order(bill, order)
        self.assertFalse(payline.pay_with_discount)

    def test_t3_fixed_date_within_deadline(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(
            date_prefered="fixed",
            date_scheduled=fields.Date.today() + timedelta(days=5),
        )
        payline = self._add_to_order(bill, order)
        self.assertTrue(payline.pay_with_discount)

    # ------------------------------------------------------------------
    # T4: Auto-reset with chatter message (FR-4)
    # ------------------------------------------------------------------

    def test_t4_auto_reset_on_confirm(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(
            date_prefered="fixed",
            date_scheduled=fields.Date.today() + timedelta(days=5),
        )
        payline = self._add_to_order(bill, order)
        self.assertTrue(payline.pay_with_discount)
        # Push the scheduled date past the discount deadline before confirming.
        order.date_scheduled = fields.Date.today() + timedelta(days=60)
        message_count_before = len(order.message_ids)
        order.draft2open()
        self.assertFalse(payline.pay_with_discount)
        move_line = self._payable_line(bill)
        self.assertEqual(payline.amount_currency, -move_line.amount_residual_currency)
        self.assertGreater(len(order.message_ids), message_count_before)

    # ------------------------------------------------------------------
    # T5-T6: Manual control (FR-2, edge case 5)
    # ------------------------------------------------------------------

    def test_t5_toggle_pay_with_discount(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(date_prefered="now")
        payline = self._add_to_order(bill, order)
        move_line = self._payable_line(bill)
        self.assertTrue(payline.pay_with_discount)
        discounted_amount = payline.amount_currency

        payline.pay_with_discount = False
        payline._onchange_pay_with_discount()
        self.assertEqual(payline.amount_currency, -move_line.amount_residual_currency)

        payline.pay_with_discount = True
        payline._onchange_pay_with_discount()
        self.assertEqual(payline.amount_currency, discounted_amount)

    def test_t6_manual_amount_edit_clears_flag(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(date_prefered="now")
        payline = self._add_to_order(bill, order)
        self.assertTrue(payline.pay_with_discount)

        payline.amount_currency = payline.amount_currency + 1.0
        payline._onchange_amount_currency_epd()
        self.assertFalse(payline.pay_with_discount)

    # ------------------------------------------------------------------
    # T7-T10: Write-off on payment generation (FR-5)
    # ------------------------------------------------------------------

    def test_t7_full_happy_path(self):
        bill = self._create_bill(fields.Date.today())
        order = self._create_order(date_prefered="now")
        self._add_to_order(bill, order)
        order.draft2open()
        self.assertEqual(order.state, "open")
        payment = order.payment_ids
        self.assertEqual(len(payment), 1)
        order.generated2uploaded()
        self.assertIn(bill.payment_state, ("paid", "in_payment"))
        self.assertEqual(bill.amount_residual, 0.0)
        write_off_lines = payment.move_id.line_ids.filtered(
            lambda line: line.display_type == "epd"
        )
        self.assertTrue(write_off_lines)

    def test_t8_write_off_equals_register_payment(self):
        """The write-off produced via the payment order must match, account
        by account and balance by balance, what the native Register Payment
        wizard produces for an identical bill."""
        bill_order = self._create_bill(fields.Date.today())
        bill_register = self._create_bill(fields.Date.today())

        order = self._create_order(date_prefered="now")
        self._add_to_order(bill_order, order)
        order.draft2open()
        order.generated2uploaded()

        register_payment = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=bill_register.ids)
            .create({"payment_date": fields.Date.today()})
            ._create_payments()
        )

        def epd_signature(move):
            lines = move.line_ids.filtered(lambda line: line.display_type == "epd")
            return sorted(
                (line.account_id.id, round(line.balance, 2)) for line in lines
            )

        self.assertEqual(
            epd_signature(order.payment_ids.move_id),
            epd_signature(register_payment.move_id),
        )
        self.assertEqual(bill_order.amount_residual, bill_register.amount_residual)

    def test_t9_computation_modes(self):
        for mode in ("included", "excluded", "mixed"):
            with self.subTest(mode=mode):
                self.pay_term_epd.early_pay_discount_computation = mode
                bill = self._create_bill(fields.Date.today())
                order = self._create_order(date_prefered="now")
                self._add_to_order(bill, order)
                order.draft2open()
                order.generated2uploaded()
                self.assertIn(bill.payment_state, ("paid", "in_payment"))
                self.assertEqual(bill.amount_residual, 0.0)

    def test_t10_mixed_grouping(self):
        eligible_bill = self._create_bill(fields.Date.today())
        non_eligible_bill = self._create_bill(
            fields.Date.today(), payment_term=self.pay_term_plain
        )
        order = self._create_order(date_prefered="now", group_lines=True)
        self._add_to_order(eligible_bill, order)
        self._add_to_order(non_eligible_bill, order)
        order.draft2open()
        payment = order.payment_ids
        self.assertEqual(len(payment), 1)
        order.generated2uploaded()
        self.assertIn(eligible_bill.payment_state, ("paid", "in_payment"))
        self.assertIn(non_eligible_bill.payment_state, ("paid", "in_payment"))
        write_off_lines = payment.move_id.line_ids.filtered(
            lambda line: line.display_type == "epd"
        )
        self.assertTrue(write_off_lines)

    # ------------------------------------------------------------------
    # T11-T12: Edge cases (refund/installments, foreign currency)
    # ------------------------------------------------------------------

    def test_t11_refund_untouched(self):
        refund = self.env["account.move"].create(
            {
                "move_type": "in_refund",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "date": fields.Date.today(),
                "ref": "EPD-REFUND-1",
                "invoice_payment_term_id": self.pay_term_epd.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 1000.0,
                            "tax_ids": [Command.set(self.tax_19.ids)],
                        }
                    )
                ],
            }
        )
        refund.action_post()
        order = self._create_order(date_prefered="now")
        payline = self._add_to_order(refund, order)
        self.assertFalse(payline.pay_with_discount)

    def test_t11_multi_installment_untouched(self):
        pay_term_installments = self.env["account.payment.term"].create(
            {
                "name": "30% now, 70% in 60 days",
                "company_id": self.company_data["company"].id,
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 30, "nb_days": 0}
                    ),
                    Command.create(
                        {"value": "percent", "value_amount": 70, "nb_days": 60}
                    ),
                ],
            }
        )
        bill = self._create_bill(
            fields.Date.today(), payment_term=pay_term_installments
        )
        order = self._create_order(date_prefered="now")
        for move_line in self._payable_line(bill):
            payline = move_line.create_payment_line_from_move_line(order)
            self.assertFalse(payline.pay_with_discount)

    def test_t12_foreign_currency_bill(self):
        foreign_currency = self.currency_data["currency"]
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "date": fields.Date.today(),
                "ref": "EPD-FOREIGN-1",
                "currency_id": foreign_currency.id,
                "invoice_payment_term_id": self.pay_term_epd.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 1000.0,
                            "tax_ids": [Command.set(self.tax_19.ids)],
                        }
                    )
                ],
            }
        )
        bill.action_post()
        order = self._create_order(date_prefered="now")
        payline = self._add_to_order(bill, order)
        self.assertTrue(payline.pay_with_discount)
        self.assertEqual(payline.currency_id, foreign_currency)
        order.draft2open()
        order.generated2uploaded()
        self.assertEqual(bill.amount_residual, 0.0)


@tagged("post_install", "-at_install")
class TestEpdPaymentOrderSepaCt(AccountTestInvoicingCommon):
    """T13: conditional test against the SEPA Credit Transfer payment
    method, skipped if `account_banking_sepa_credit_transfer` is not
    installed in the test database."""

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.sct_method = cls.env["account.payment.method"].search(
            [("code", "=", "sepa_credit_transfer"), ("payment_type", "=", "outbound")]
        )

    def test_t13_sepa_ct_instd_amt(self):
        if not self.sct_method:
            self.skipTest("account_banking_sepa_credit_transfer is not installed")
        tax_19 = self.env["account.tax"].create(
            {
                "name": "Tax 19% SCT",
                "amount": 19.0,
                "amount_type": "percent",
                "type_tax_use": "purchase",
            }
        )
        pay_term_epd = self.env["account.payment.term"].create(
            {
                "name": "2/10 net 30 SCT",
                "company_id": self.company_data["company"].id,
                "early_discount": True,
                "discount_percentage": 2.0,
                "discount_days": 10,
                "line_ids": [
                    Command.create(
                        {"value": "percent", "value_amount": 100, "nb_days": 30}
                    )
                ],
            }
        )
        bank_journal = self.env["account.journal"].create(
            {
                "name": "Test Bank Journal SCT",
                "type": "bank",
                "bank_acc_number": "GB33BUKB20201555555555",
            }
        )
        self.partner_a.bank_ids = [
            Command.create(
                {"acc_number": "NL91ABNA0417164300", "partner_id": self.partner_a.id}
            )
        ]
        payment_mode = self.env["account.payment.mode"].create(
            {
                "name": "Test SCT mode",
                "fixed_journal_id": bank_journal.id,
                "bank_account_link": "fixed",
                "payment_method_id": self.sct_method.id,
            }
        )
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": fields.Date.today(),
                "date": fields.Date.today(),
                "ref": "EPD-SCT-1",
                "invoice_payment_term_id": pay_term_epd.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 1000.0,
                            "tax_ids": [Command.set(tax_19.ids)],
                        }
                    )
                ],
            }
        )
        bill.action_post()
        order = self.env["account.payment.order"].create(
            {
                "payment_mode_id": payment_mode.id,
                "payment_type": "outbound",
                "date_prefered": "now",
                "journal_id": bank_journal.id,
            }
        )
        move_line = bill.line_ids.filtered(
            lambda line: line.account_id.account_type == "liability_payable"
        )
        payline = move_line.create_payment_line_from_move_line(order)
        self.assertTrue(payline.pay_with_discount)
        order.draft2open()
        payment_file_str, _filename = order.generate_payment_file()
        root = etree.fromstring(payment_file_str)
        ns = {"ns": root.nsmap[None]}
        instd_amt = root.findall(".//ns:InstdAmt", ns)
        self.assertEqual(len(instd_amt), 1)
        self.assertAlmostEqual(
            float(instd_amt[0].text), payline.amount_currency, places=2
        )

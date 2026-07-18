# Copyright 2026 mikrowerk - Guenther Froestl
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, fields, models


class AccountPaymentLine(models.Model):
    _inherit = "account.payment.line"

    pay_with_discount = fields.Boolean(
        help="The proposed amount is reduced by the early payment discount "
        "granted by the payment term of the related bill.",
    )
    discount_date = fields.Date(
        help="Deadline to pay this line at the discounted amount in order "
        "for the early payment discount to be granted.",
    )
    discount_amount_currency = fields.Monetary(
        string="Amount with Discount",
        currency_field="currency_id",
        help="Amount to pay if the early payment discount is taken.",
    )
    discount_expiring = fields.Boolean(
        compute="_compute_discount_expiring",
        help="The discount deadline is in the past relative to the "
        "order's reference date, but the line is still flagged to be "
        "paid with the discount.",
    )

    @api.depends("pay_with_discount", "discount_date", "order_id.date_prefered")
    def _compute_discount_expiring(self):
        for line in self:
            if (
                not line.pay_with_discount
                or not line.discount_date
                or not line.order_id
            ):
                line.discount_expiring = False
                continue
            reference_date = line.order_id._epd_reference_date(payment_line=line)
            line.discount_expiring = line.discount_date < reference_date

    def _epd_full_residual_amount(self):
        self.ensure_one()
        amount = self.move_line_id.amount_residual_currency
        if self.payment_type == "outbound":
            amount = -amount
        return amount

    @api.onchange("pay_with_discount")
    def _onchange_pay_with_discount(self):
        for line in self:
            if line.pay_with_discount:
                line.amount_currency = line.discount_amount_currency
            elif line.move_line_id:
                line.amount_currency = line._epd_full_residual_amount()

    @api.onchange("amount_currency")
    def _onchange_amount_currency_epd(self):
        for line in self:
            if (
                line.pay_with_discount
                and line.currency_id.compare_amounts(
                    line.amount_currency, line.discount_amount_currency
                )
                != 0
            ):
                line.pay_with_discount = False

    def _prepare_account_payment_vals(self):
        """FR-5: inject the write-off lines (discount income/expense + tax
        adjustment) for the payment lines paid with discount in this group,
        so the resulting account.payment fully reconciles the underlying
        bills."""
        vals = super()._prepare_account_payment_vals()
        discounted_move_lines = self.filtered("pay_with_discount").mapped(
            "move_line_id"
        )
        if discounted_move_lines:
            vals["write_off_line_vals"] = self.env[
                "epd.adapter"
            ]._epd_get_write_off_vals(discounted_move_lines)
        return vals

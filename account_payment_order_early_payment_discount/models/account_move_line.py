# Copyright 2026 mikrowerk - Guenther Froestl
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _prepare_payment_line_vals(self, payment_order):
        """FR-1: apply the early payment discount, if eligible, when a
        payment line is created from this move line. Only outbound orders
        (vendor bills) are in scope; inbound (debit) orders are left
        untouched."""
        vals = super()._prepare_payment_line_vals(payment_order)
        if payment_order.payment_type != "outbound":
            return vals
        epd_adapter = self.env["epd.adapter"]
        reference_date = payment_order._epd_reference_date(move_line=self)
        if not epd_adapter._epd_is_eligible(self, reference_date):
            return vals
        discount_vals = epd_adapter._epd_get_discount_vals(self)
        # account.payment.line.amount_currency uses the opposite sign of the
        # core aml residual for outbound orders (see the base
        # `_prepare_payment_line_vals`); mirror that here so
        # `discount_amount_currency` stays comparable to `amount_currency`.
        discount_amount = -discount_vals["discount_amount_currency"]
        vals.update(
            {
                "pay_with_discount": True,
                "discount_date": discount_vals["discount_date"],
                "discount_amount_currency": discount_amount,
                "amount_currency": discount_amount,
            }
        )
        return vals

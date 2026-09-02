# Copyright 2026 mikrowerk - Guenther Froestl
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import api, fields, models


class EpdAdapter(models.AbstractModel):
    """Adapter around the Odoo CE Early Payment Discount (EPD) private API.

    This is the ONLY file in the module allowed to call core `_`-prefixed EPD
    methods or read core EPD fields directly. When porting to a newer Odoo
    version, only this file should need changes.
    """

    _name = "epd.adapter"
    _description = "Early Payment Discount core API adapter"

    @api.model
    def _epd_is_eligible(self, move_line, reference_date):
        """Return True if ``move_line`` (a payment term line) is eligible for
        the early payment discount at ``reference_date``.

        Wraps `account.move._is_eligible_for_early_payment_discount()` and
        additionally rejects discounts that round to zero (edge case: the
        discount amount equals the residual at currency precision).
        """
        move = move_line.move_id
        if not move._is_eligible_for_early_payment_discount(
            move_line.currency_id, reference_date
        ):
            return False
        currency = move_line.currency_id
        return (
            currency.compare_amounts(
                move_line.discount_amount_currency, move_line.amount_residual_currency
            )
            != 0
        )

    @api.model
    def _epd_get_discount_vals(self, move_line):
        """Return the discount deadline and discounted amount read from the
        core computed fields on the payment term line."""
        return {
            "discount_date": move_line.discount_date,
            "discount_amount_currency": move_line.discount_amount_currency,
        }

    @api.model
    def _epd_get_write_off_vals(self, move_lines):
        """Build the ``write_off_line_vals`` list for `account.payment`,
        for a set of payment term lines (``move_lines``) that are fully paid
        with their early payment discount.

        Mirrors the value-list construction used by core
        `account.payment.register._create_payment_vals_from_wizard()` when
        `early_payment_discount_mode` is set, then flattens the result of
        `account.move._get_invoice_counterpart_amls_for_early_payment_discount()`
        into a single list.
        """
        if not move_lines:
            return []
        today = fields.Date.context_today(self)
        aml_values_list = [
            {
                "aml": aml,
                "amount_currency": -aml.amount_residual_currency,
                "balance": aml.currency_id._convert(
                    -aml.amount_residual_currency,
                    aml.company_currency_id,
                    aml.company_id,
                    today,
                ),
            }
            for aml in move_lines
        ]
        early_payment_values = self.env[
            "account.move"
        ]._get_invoice_counterpart_amls_for_early_payment_discount(aml_values_list, 0.0)
        return [
            vals
            for key in ("base_lines", "tax_lines", "term_lines")
            for vals in early_payment_values[key]
        ]

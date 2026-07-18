# Copyright 2026 mikrowerk - Guenther Froestl
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

from odoo import _, fields, models


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def _epd_reference_date(self, move_line=None, payment_line=None):
        """Return the date at which early payment discount eligibility must
        be checked for this order, following the same ``date_prefered``
        rules used to compute the payment line's own execution date (see
        `draft2open()`).

        :param move_line: the underlying ``account.move.line`` being turned
            into a payment line (used before the payment line exists, i.e.
            at line-creation time).
        :param payment_line: the ``account.payment.line`` already created
            (used on re-check, e.g. `draft2open()`).
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.date_prefered == "fixed":
            return self.date_scheduled or today
        if self.date_prefered == "due":
            if payment_line is not None:
                return payment_line.ml_maturity_date or today
            if move_line is not None:
                return move_line.date_maturity or today
            return today
        return today

    def _epd_recheck_discount_lines(self):
        """FR-4: re-validate every ``pay_with_discount`` payment line against
        the current reference date, resetting it to the full residual amount
        when the discount is no longer available. Never blocks; the reset is
        reported in the order chatter."""
        self.ensure_one()
        epd_adapter = self.env["epd.adapter"]
        reset_lines = []
        for payline in self.payment_line_ids.filtered("pay_with_discount"):
            move_line = payline.move_line_id
            reference_date = self._epd_reference_date(payment_line=payline)
            if not epd_adapter._epd_is_eligible(move_line, reference_date):
                reset_lines.append(payline)
        if not reset_lines:
            return
        log_lines = []
        for payline in reset_lines:
            old_amount = payline.amount_currency
            full_residual = payline.move_line_id.amount_residual_currency
            if self.payment_type == "outbound":
                full_residual = -full_residual
            payline.write(
                {"pay_with_discount": False, "amount_currency": full_residual}
            )
            log_lines.append(
                _(
                    "%(name)s: %(old).2f → %(new).2f",
                    name=payline.name or payline.communication,
                    old=old_amount,
                    new=full_residual,
                )
            )
        self.message_post(
            body=_(
                "Early payment discount no longer available for the following "
                "payment lines. Amount has been reset to the full residual "
                "amount:"
            )
            + "<ul><li>"
            + "</li><li>".join(log_lines)
            + "</li></ul>"
        )

    def draft2open(self):
        for order in self:
            order._epd_recheck_discount_lines()
        return super().draft2open()

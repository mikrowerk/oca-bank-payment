Odoo CE ships native Early Payment Discount (EPD, "Skonto") support on payment
terms, but it is only applied through the Register Payment wizard. This module
closes that gap for the OCA payment order flow
(`account_payment_order` → SEPA Credit Transfer): when journal items eligible
for an early payment discount are added to a payment order, the proposed
payment amount is automatically reduced by the discount, provided the discount
deadline is met at the planned execution date. On payment generation, the
discount is written off automatically (discount income/expense account plus
tax adjustment), so the vendor bill is fully reconciled, exactly as the native
Register Payment wizard does.

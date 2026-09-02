1. Post a vendor bill using a payment term with an Early Payment Discount
   (`Early Discount` enabled on the payment term).
2. Add the bill to a payment order (via the *Add to Payment Order* action or
   the *Populate* wizard). If the discount deadline can still be met, the
   payment line is created with the discounted amount and the
   "Pay with Discount" flag set.
3. Confirm the payment order (`Confirm`). If the discount deadline is no
   longer met by then, the affected lines are automatically reset to the full
   residual amount and a note is posted in the order's chatter.
4. Generate/upload the payment as usual. The resulting payment fully
   reconciles the bill: the bank line carries the discounted amount, and a
   write-off line books the discount (with the correct tax adjustment) against
   the full invoice amount.

Users can toggle "Pay with Discount" off/on manually on a payment line while
the order is still editable.

# Specification: `account_payment_order_early_payment_discount`

**Target repository:** [OCA/bank-payment](https://github.com/OCA/bank-payment) **Target
branches:** 17.0 (primary), forward ports to 18.0 and 19.0 **License:** AGPL-3
**Status:** Draft for implementation (intended as OCA pull request) **Audience:** Claude
Code / developer implementing the module

---

## 1. Goal

Odoo CE 16+ ships native _Early Payment Discount_ (EPD, German: _Skonto_) support on
payment terms. However, this discount is only applied when paying invoices through the
standard **Register Payment** wizard (single payment / "mark as paid"). The OCA payment
order flow (`account_payment_order` → SEPA credit transfer file via
`account_banking_sepa_credit_transfer`) ignores EPD entirely: payment lines are always
created with the **full residual amount**.

This module closes that gap:

> When journal items eligible for an early payment discount are added to a payment
> order, the proposed payment amount is **automatically reduced by the discount**,
> provided the discount deadline is met at the planned execution date. On payment
> generation, the discount is **written off automatically** (discount income/expense
> account plus tax adjustment) so that the vendor bill is fully reconciled — exactly as
> the native Register Payment wizard does.

The generated SEPA `pain.001` file requires **no changes**: it serializes the (already
reduced) payment line amounts.

## 2. Scope and non-goals

### In scope

- Outbound payment orders (`payment_type = outbound`, vendor bills) processed via
  `account_payment_order`, and therefore SEPA Credit Transfer files.
- Automatic application of the **native Odoo EPD** (single discount stage defined on
  `account.payment.term`: `early_discount`, `discount_percentage`, `discount_days`).
- Correct accounting write-off including **tax adjustment** according to the company
  setting `early_pay_discount_computation` (`included` / `excluded` / `mixed`).
- Auto-reset to the full amount when the discount deadline is exceeded (see FR-4).

### Out of scope (explicitly)

- Debit orders / SEPA Direct Debit (`inbound`). The design must not break them, but no
  discount logic is applied to them.
- Multi-stage discounts (e.g. 3% within 10 days, 2% within 20 days) and tolerance days.
  These are candidates for a future extension module and must not leak into this
  module's data model.
- Re-implementation of any discount computation. **All** amount, deadline and tax logic
  is delegated to Odoo CE core (see §4 Adapter layer).
- `OCA/bank-payment-alternative` (`account_payment_batch_oca`). A later port must be
  possible with minimal effort thanks to the adapter layer, but is not part of this
  deliverable.

## 3. Module metadata

| Key            | Value                                                                                   |
| -------------- | --------------------------------------------------------------------------------------- |
| Technical name | `account_payment_order_early_payment_discount`                                          |
| Summary        | Apply early payment discounts on payment orders                                         |
| Version        | `17.0.1.0.0`                                                                            |
| Category       | `Banking addons`                                                                        |
| Depends        | `account_payment_order` (nothing else — **not** `account_banking_sepa_credit_transfer`) |
| Author         | `mikrowerk Guenther Froestl, Odoo Community Association (OCA)`                          |
| Website        | `https://github.com/OCA/bank-payment`                                                   |
| Maintainers    | `https://github.com/mikrowerk`                                                          |
| Application    | `False`, `installable: True`, `auto_install: False`                                     |

Rationale for the dependency choice: the discount belongs to the _payment order layer_.
Any file format built on top of `account.payment.line` (SCT, and in principle other
formats) benefits automatically.

## 4. Architecture — adapter layer around Odoo CE

### 4.1 Design rule

The module **reuses** the Odoo CE EPD data model and computation, but every call into
core private API is **encapsulated in one adapter file**. No other file in the module
may call a core `_`-prefixed EPD method or read core EPD fields directly (payment-term
fields excepted in views). When porting to 18.0/19.0, only the adapter file may need
changes.

### 4.2 Core touchpoints (verified)

The following core API has been verified to exist **with identical signatures on Odoo
17.0, 18.0 and 19.0** (`addons/account/models/account_move.py` /
`account_move_line.py`):

| Core API                                                                                               | Purpose                                                                                   |
| ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `account.move._is_eligible_for_early_payment_discount(currency, reference_date)`                       | Eligibility check (full residual open, deadline not passed, single currency)              |
| `account.move._get_invoice_counterpart_amls_for_early_payment_discount(aml_values_list, open_balance)` | Builds the write-off line values incl. tax adjustment per`early_pay_discount_computation` |
| `account.move.line.discount_date` (Date)                                                               | Discount deadline on the payment term line                                                |
| `account.move.line.discount_amount_currency` (Monetary)                                                | Residual to pay**if** discount is taken (invoice currency)                                |
| `account.move.line.discount_balance` (Monetary)                                                        | Same in company currency                                                                  |

### 4.3 Adapter interface

File: `models/epd_adapter.py`, abstract model `epd.adapter` (`_name = "epd.adapter"`,
`_description = "Early Payment Discount core API adapter"`).

```python
class EpdAdapter(models.AbstractModel):
    _name = "epd.adapter"
    _description = "Early Payment Discount core API adapter"

    @api.model
    def _epd_is_eligible(self, move_line, reference_date):
        """Return True if the payment term line's move is eligible for EPD
        at ``reference_date``. Wraps
        account.move._is_eligible_for_early_payment_discount()."""

    @api.model
    def _epd_get_discount_vals(self, move_line):
        """Return dict(discount_date=?, discount_amount_currency=?)
        read from the core computed fields on the payment term line."""

    @api.model
    def _epd_get_write_off_vals(self, move_lines):
        """Return a list of write_off_line_vals dicts for account.payment,
        built via
        account.move._get_invoice_counterpart_amls_for_early_payment_discount().
        Input: eligible payment term lines being paid with discount.
        The per-aml input dict mirrors the one built by
        account.payment.register._create_payment_vals_from_wizard()
        (keys: aml, amount_currency, balance)."""
```

Implementation note for `_epd_get_write_off_vals`: replicate the value-list construction
used by core `account.payment.register` when `early_payment_discount_mode` is set (per
aml:
`{"aml": aml, "amount_currency": -aml.amount_residual_currency, "balance": currency.round(-aml.amount_residual_currency * conversion_rate)}`),
pass `open_balance = 0.0` for the fully-discounted case, then flatten the returned
`dict[account, list[vals]]` into a single `write_off_line_vals` list. Keep this logic
**only** here.

## 5. Functional requirements

### FR-1 — Automatic discount on payment line creation

When payment lines are created from journal items (wizard `account.payment.line.create`,
the _Add to Payment Order_ action on vendor bills, or
`account.move.line.create_payment_line_from_move_line()`), each line whose move is
EPD-eligible at the **reference date** (FR-3) is created with:

- `amount_currency` = core `discount_amount_currency` of the payment term line (i.e.
  residual minus discount),
- `pay_with_discount = True`,
- `discount_date` and `discount_amount_currency` copied onto the payment line.

Non-eligible lines behave exactly as before. This applies automatically to **all**
eligible items — no opt-in checkbox (per product decision).

Hook: override `account.move.line._prepare_payment_line_vals(payment_order)`.

### FR-2 — Per-line manual control

`account.payment.line` gets a user-editable boolean `pay_with_discount` (only while the
order is in `draft`/`open` as far as the existing framework allows edits). Toggling it
switches `amount_currency` between full residual and discounted amount via an
onchange/compute. Users can thus opt out per line; they can also opt in manually for a
line the system reset (at their own risk — see FR-4 re-check).

### FR-3 — Reference date

The eligibility reference date is determined on the payment order:

```
order._epd_reference_date():
    date_prefered == "fixed"  -> date_scheduled
    date_prefered == "due"    -> the line's own ml_maturity_date (per line!)
    date_prefered == "now"    -> today
```

For `date_prefered == "due"` the check must be evaluated **per payment line** against
its maturity date. Implement `_epd_reference_date(payment_line=None)` accordingly.

### FR-4 — Deadline re-check with auto-reset (product decision)

On `account.payment.order.draft2open()` (order confirmation), every line with
`pay_with_discount = True` is re-validated against the (possibly changed) reference
date:

- Still eligible → unchanged.
- **No longer eligible** (deadline passed, invoice state changed, partial payment
  happened meanwhile) → the line is **automatically reset** to the full residual amount:
  `pay_with_discount = False`, `amount_currency = residual`. The reset is logged in the
  order chatter (`message_post`) listing the affected invoices/amounts, so the operator
  sees why totals changed. **No blocking error.**

### FR-5 — Write-off on payment generation

`account.payment.line._prepare_account_payment_vals()` is extended: if the grouped lines
contain `pay_with_discount` lines, add
`write_off_line_vals = adapter._epd_get_write_off_vals(...)` to the returned dict.
`account.payment` natively supports `write_off_line_vals` in
`_prepare_move_line_default_vals()`; the payment move then contains bank (discounted
amount), discount income/expense and tax-adjustment lines against the **full** payable
amount. Consequently the existing `generated2uploaded()` reconciliation closes the
invoice completely **without any change** to that method.

Constraint: if line grouping (`payment_line_hashcode`) would merge discounted and
non-discounted lines into one `account.payment`, the write-off vals are computed per
underlying move line, so mixing is safe. Add a test for this.

### FR-6 — SEPA file untouched

No override in the pain.001 generation. Amount in `<InstdAmt>` = payment line amount
(already discounted). The remittance info (`communication`) keeps referencing the
invoice as today.

### FR-7 — Idempotence & cancellation

`action_cancel` / `cancel2draft` must leave no orphaned state: discount fields live on
the payment line only; nothing is written to the invoice before payment generation.
Re-running `draft2open` after `cancel2draft` re-evaluates FR-4.

## 6. Data model changes

`account.payment.line` (new fields, all `readonly=False` only in editable states):

| Field                      | Type                   | Notes                                    |
| -------------------------- | ---------------------- | ---------------------------------------- |
| `pay_with_discount`        | Boolean                | default from FR-1; user-editable (FR-2)  |
| `discount_date`            | Date                   | snapshot from move line at line creation |
| `discount_amount_currency` | Monetary (currency_id) | amount to pay**with** discount           |

No fields are added to `account.payment.order`, `account.payment.mode` or `account.move`
in v1 (auto-apply is unconditional; a mode-level kill switch can be a follow-up).

## 7. UI

- `account.payment.line` tree/form (inherit the views shipped by
  `account_payment_order`): add `pay_with_discount` (widget `boolean_toggle`),
  `discount_date`; `decoration-success` on lines with `pay_with_discount`,
  `decoration-warning` (via computed helper field `discount_expiring`, non-stored) when
  `discount_date` < reference date while `pay_with_discount` is still set.
- Wizard `account.payment.line.create`: informational note (no new options in v1).
- Order form: nothing new; chatter carries FR-4 reset messages.

## 8. Edge cases (must be handled + tested)

1. **Partial payments / partially reconciled bills** — core
   `_is_eligible_for_early_payment_discount` already returns False; line falls back to
   full residual. Test it.
2. **Payment terms with multiple installments** — core marks such moves ineligible for
   EPD; must pass through unchanged.
3. **Credit notes in the order** (`in_refund`) — never discounted; amounts unchanged.
4. **Foreign currency bills** — discount amount taken in invoice currency
   (`discount_amount_currency`); write-off conversion is delegated to the adapter/core.
5. **Manual amount edit** after auto-apply — editing `amount_currency` manually on a
   `pay_with_discount` line sets `pay_with_discount = False` (onchange) to keep the
   write-off consistent with the paid amount.
6. **Grouped payments** mixing discounted and non-discounted lines (see FR-5).
7. **`date_prefered = "due"`** — per-line reference date (FR-3).
8. **Zero/rounding discounts** — if `residual - discount_amount_currency` is zero at
   currency rounding, treat as non-eligible.
9. **Company setting variants** — `early_pay_discount_computation` in `included`,
   `excluded`, `mixed`: write-off must match what Register Payment produces (assert
   equality of resulting move line values in tests).

## 9. Repository & OCA conventions

- Module lives in `OCA/bank-payment`, branch `17.0`, top-level directory
  `account_payment_order_early_payment_discount/`.
- Follow the **oca-addons-repo-template**: run the repo's `pre-commit` (black, isort,
  flake8, pylint-odoo, prettier for XML) — `pre-commit run -a` must pass.
- **Readme fragments** under `readme/` (`DESCRIPTION.md`, `CONFIGURE.md`, `USAGE.md`,
  `CONTRIBUTORS.md`, `CREDITS.md`, `ROADMAP.md`); never hand-edit the generated
  `README.rst`. ROADMAP must mention: SDD support, multi-stage discounts, port to
  `bank-payment-alternative`.
- Security: no new models requiring ACLs (only field additions + abstract model → no
  `ir.model.access.csv` needed; abstract models need none).
- Commit style: single commit `[ADD] account_payment_order_early_payment_discount`
  (squash fixups), sign-off per OCA CLA.
- PR flow: open an **RFC issue** on OCA/bank-payment first (link this spec), then PR
  against `17.0`; forward-port PRs to `18.0`/`19.0` as separate PRs. Runboat must be
  green.
- i18n: `i18n/` folder generated by the OCA bot — do not commit `.po` files manually
  except `de.po` if provided.

## 10. Test plan (`tests/test_epd_payment_order.py`, `TransactionCase`)

Common fixture: company with configurable `early_pay_discount_computation`; payment term
"2/10 net 30" (`early_discount=True`, `discount_percentage=2`, `discount_days=10`);
vendor bill 1,000.00 (19% tax) posted today; payment mode using a generic manual payment
method **plus** one test class running against the SEPA CT method if
`account_banking_sepa_credit_transfer` is installed (use `@tagged` + conditional skip,
no hard dependency).

| #   | Test                                                                                          | Assertions                                                                                          |
| --- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| T1  | Eligible bill → wizard fills order                                                            | line amount ==`discount_amount_currency`; `pay_with_discount` True; `discount_date` set             |
| T2  | Deadline already passed at creation                                                           | full residual; flag False                                                                           |
| T3  | `date_scheduled` beyond deadline (`date_prefered="fixed"`)                                    | auto-created line not discounted                                                                    |
| T4  | Auto-reset: line created discounted, then`date_scheduled` moved past deadline, `draft2open()` | amount back to full residual; flag False; chatter message posted                                    |
| T5  | Toggle`pay_with_discount` off/on                                                              | amount switches full ↔ discounted                                                                   |
| T6  | Manual amount edit clears flag                                                                | edge case 5                                                                                         |
| T7  | Full happy path to`generated2uploaded`                                                        | bill`payment_state` in `paid`/`in_payment`; payment move contains write-off + tax lines; residual 0 |
| T8  | Write-off equals Register Payment                                                             | run native wizard on a clone bill; compare write-off move line (account, balance, tax) sets         |
| T9  | Computation modes`included`/`excluded`/`mixed`                                                | T7 green in all three                                                                               |
| T10 | Mixed grouping (two bills, one eligible) into one payment                                     | payment amount, write-off only for eligible bill, both bills reconciled                             |
| T11 | Refund / installment terms untouched                                                          | amounts unchanged, flag False                                                                       |
| T12 | Foreign currency bill                                                                         | discounted amount in invoice currency; reconciliation closes                                        |
| T13 | SEPA CT (conditional)                                                                         | generated pain.001`InstdAmt` equals discounted amount                                               |

Coverage goal ≥ 90% for the new module (codecov gate of the repo).

## 11. Directory layout

```
account_payment_order_early_payment_discount/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── epd_adapter.py            # ONLY file touching core EPD private API
│   ├── account_move_line.py      # _prepare_payment_line_vals override
│   ├── account_payment_line.py   # fields, onchange, _prepare_account_payment_vals
│   └── account_payment_order.py  # _epd_reference_date, draft2open auto-reset
├── views/
│   └── account_payment_order.xml # payment line tree/form inherits
├── readme/
│   ├── DESCRIPTION.md
│   ├── CONFIGURE.md
│   ├── USAGE.md
│   ├── ROADMAP.md
│   └── CONTRIBUTORS.md
└── tests/
    ├── __init__.py
    └── test_epd_payment_order.py
```

## 12. Implementation plan for Claude Code

1. Scaffold module per §11 against a checkout of `OCA/bank-payment` branch `17.0` (Odoo
   17 CE dev environment; run existing `account_payment_order` tests first as a
   baseline).
2. Implement `epd_adapter.py` incl. docstrings referencing the exact core methods
   (§4.2/4.3). Unit-test the adapter in isolation (eligibility yes/no, write-off vals
   shape).
3. Implement FR-1/FR-3 (`account_move_line.py`, `account_payment_order.py`); tests
   T1–T3.
4. Implement FR-2 + edge case 5 (`account_payment_line.py`); tests T5–T6.
5. Implement FR-4 auto-reset + chatter; test T4.
6. Implement FR-5 write-off injection; tests T7–T12 (T8 is the correctness anchor —
   build it early).
7. Views (§7), readme fragments, `de.po` translation (optional).
8. `pre-commit run -a`, full test suite of the whole repo (`account_payment_order` must
   stay green), coverage check.
9. Conditional SEPA test T13.
10. Prepare RFC issue text + PR description (summary = §1, link spec, screenshots of the
    payment line UI and chatter reset message).

## 13. Acceptance criteria

- All tests in §10 pass on Odoo 17.0 CE with only `account_payment_order` (+ optional
  SEPA CT module) installed; repo pre-commit clean.
- Removing/uninstalling the module leaves existing payment orders functional (fields are
  additive; no core behavior overridden when no line has the flag).
- Grep proof: outside `models/epd_adapter.py` there is **no** occurrence of
  `_is_eligible_for_early_payment_discount` or
  `_get_invoice_counterpart_amls_for_early_payment_discount`.
- A dry-run forward-port to 18.0 requires changes only in `epd_adapter.py` (expected:
  none, API verified identical) plus manifest version bump.

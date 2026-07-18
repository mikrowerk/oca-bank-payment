# Plan: `account_payment_order_early_payment_discount`

Source spec: `.features/.specs/SPEC_account_payment_order_early_payment_discount.md`

## 0. Critical review of the spec

The spec was cross-checked against the actual Odoo 17.0 core source
(`odoo-17/addons/account/models/account_move.py`, `account_move_line.py`,
`account_payment.py`, `account_payment_term.py`,
`wizard/account_payment_register.py`) and against the current
`account_payment_order` module in this checkout. Findings:

- All core touchpoints in §4.2 exist with the exact signatures claimed:
  `account.move._is_eligible_for_early_payment_discount(currency, reference_date)`,
  `account.move._get_invoice_counterpart_amls_for_early_payment_discount(aml_values_list, open_balance)`,
  `account.move.line.discount_date/discount_amount_currency/discount_balance`.
- The implementation note in §4.3 for `_epd_get_write_off_vals` matches the wizard's
  actual construction in `account_payment_register.py::_create_payment_vals_from_wizard`
  almost verbatim: `{'aml': aml, 'amount_currency': -aml.amount_residual_currency,
  'balance': aml.currency_id._convert(-aml.amount_residual_currency,
  aml.company_currency_id, date=self.payment_date)}`. Use `_convert` (not
  `currency.round(... * conversion_rate)` as literally written in the spec) — it's the
  exact core idiom and avoids reimplementing rate lookup.
- Hook points named in FR-1 (`account.move.line._prepare_payment_line_vals`) and FR-5
  (`account.payment.line._prepare_account_payment_vals`) exist verbatim in
  `account_payment_order/models/account_move_line.py` and `account_payment_line.py`.
- FR-3's per-`date_prefered` pseudocode mirrors the date computation already inlined in
  `account.payment.order.draft2open()` (lines ~298-303 of `account_payment_order.py`),
  confirming the reference-date design is faithful to existing behavior. One nuance the
  spec doesn't spell out: `draft2open` clamps the requested date with
  `max(today, requested_date)` — never a past payment date. Resolution: this clamp is
  irrelevant to EPD eligibility (which should look at the *unclamped* due/scheduled date
  to decide if the discount window is genuinely met) — `_epd_reference_date` will **not**
  apply the clamp. This matches the spirit of FR-3/FR-4 (deadline re-check uses the real
  dates, not the payment execution floor).
- Location check: `oca-bank-payment` is a git submodule pointing at the user's own fork
  (`git@github.com:mikrowerk/oca-bank-payment.git`), currently checked out on branch
  `feature/TOM-102-early-payment-for-sepa-credit-transfers` — a branch already named for
  this exact feature. This resolves the apparent conflict with the root CLAUDE.md rule
  that `oca-*` directories are third-party and not to be changed: that rule protects
  *existing* vendored OCA module code from being modified, not a brand-new, additive
  module scaffolded in the user's own fork for eventual upstream contribution (which is
  literally what this spec is for). No changes to `account_payment_order` itself are
  made — only new files plus the additive hooks the spec already designed for.
- A local, runnable test environment exists: `odoo-bin` at
  `odoo-17/odoo-bin`, `odoo.conf` at the repo root already lists `oca-bank-payment` on
  `addons_path`, and a local Postgres is configured. Tests will be run for real, not just
  statically reviewed.
- `.pre-commit-config.yaml` and `.copier-answers.yml` (oca-addons-repo-template,
  `whool` + `oca-gen-addon-readme`) are present at the repo root, confirming the readme
  fragment / manifest conventions in §9 apply as described.

### Assumptions locked in (no further product ambiguity — proceeding without blocking questions)

1. **Scope of this pass = 17.0 only.** §12's 10-step plan only scaffolds against 17.0;
   forward ports to 18.0/19.0 are explicitly future work per §2 and are **not** done
   here.
2. **No GitHub-facing actions.** Step 10 of §12 ("RFC issue text + PR description") is
   prepared as text only. No branch push, no PR, no issue is created — that requires the
   user's explicit go-ahead (hard-to-reverse, visible-to-others action).
3. **Test execution** uses a disposable local Postgres database created for this task
   only (dropped afterwards), not any long-lived project database.
4. **`pre-commit run`** is scoped to the new module's files only (`--files <new files>`),
   not `-a` across the whole `oca-bank-payment` repo, to avoid reformatting unrelated
   pre-existing files as a side effect.
5. **Reference-date computation split**: the spec's `_epd_reference_date(payment_line=None)`
   is needed in two different moments that don't share a payment-line record yet:
   - FR-1 (line creation, hook on `account.move.line._prepare_payment_line_vals`): no
     `account.payment.line` exists yet. Implemented as
     `order._epd_reference_date(move_line=self)`, reading `move_line.date_maturity`
     directly for the `"due"` case.
   - FR-4 (`draft2open` re-check): the `account.payment.line` already exists and its
     `ml_maturity_date` (related to the same underlying `date_maturity`) is available.
     Implemented as `order._epd_reference_date(payment_line=payline)`.
   Both branches resolve to the same underlying value; the method just accepts whichever
   record is at hand. This keeps a single method (per spec) rather than forking it into
   two.
6. **Zero/rounding discount (edge case 8)**: eligibility requires
   `currency.compare_amounts(discount_amount_currency, residual) != 0` in addition to the
   core eligibility check — i.e. reject "eligible but discount rounds to nothing".

## 1. Directory layout (per spec §11 — unchanged)

```
account_payment_order_early_payment_discount/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── epd_adapter.py
│   ├── account_move_line.py
│   ├── account_payment_line.py
│   └── account_payment_order.py
├── views/
│   └── account_payment_order.xml
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

`__manifest__.py` per §3: `depends: ["account_payment_order"]` only, version
`17.0.1.0.0`, category `Banking addons`, author
`"mikrowerk Guenther Froestl, Odoo Community Association (OCA)"`. No
`security/ir.model.access.csv` (no new models — only field additions + one abstract
model).

## 2. Implementation steps

1. **Scaffold** the module skeleton (manifest, `__init__.py` files, empty readme
   fragments) so it installs cleanly with zero behavior change first.
2. **`models/epd_adapter.py`** — `epd.adapter` `AbstractModel` with the 3 methods from
   §4.3:
   - `_epd_is_eligible(move_line, reference_date)` → wraps
     `move_line.move_id._is_eligible_for_early_payment_discount(move_line.currency_id, reference_date)`
     **plus** the rounding guard from assumption 6.
   - `_epd_get_discount_vals(move_line)` → `{"discount_date": move_line.discount_date,
     "discount_amount_currency": move_line.discount_amount_currency}`.
   - `_epd_get_write_off_vals(move_lines)` → builds `aml_values_list` exactly as the
     core wizard does (assumption/finding above), calls
     `env["account.move"]._get_invoice_counterpart_amls_for_early_payment_discount(aml_values_list, 0.0)`,
     flattens the returned `dict[account, list[vals]]` across `base_lines`, `tax_lines`,
     `term_lines` (skip `exchange_lines` unless a multi-currency test proves it
     necessary — same-currency is the only case exercised by T1-T11; T12 will confirm
     whether it's needed and the adapter will be extended then, not speculatively now).
3. **`models/account_move_line.py`** — override `_prepare_payment_line_vals` (FR-1):
   compute `reference_date = payment_order._epd_reference_date(move_line=self)`; if
   `epd_adapter._epd_is_eligible(self, reference_date)`, override `amount_currency` with
   the (sign-adjusted, same as existing outbound negation) discount amount and set
   `pay_with_discount=True` + snapshot `discount_date`/`discount_amount_currency` in the
   returned vals dict; otherwise unchanged (`pay_with_discount=False`).
4. **`models/account_payment_order.py`**:
   - `_epd_reference_date(self, move_line=None, payment_line=None)` per FR-3 (no clamp,
     see review note).
   - Override `draft2open()`: **before** the existing loop's per-line date computation,
     re-validate every `pay_with_discount=True` line against the freshly computed
     reference date; on ineligibility, reset `pay_with_discount=False` and
     `amount_currency` to the full residual (re-derive via `move_line_id`), collect the
     affected lines/amounts, and `message_post` a single summary once per order after
     the loop (FR-4). Must not raise — resets are logged, not blocking.
5. **`models/account_payment_line.py`**:
   - New fields `pay_with_discount` (Boolean), `discount_date` (Date),
     `discount_amount_currency` (Monetary, `currency_field="currency_id"`).
   - `discount_expiring` computed, non-stored Boolean for the view decoration (§7):
     true when `pay_with_discount` and `discount_date` is before the order's current
     reference date.
   - `@api.onchange("pay_with_discount")` — flips `amount_currency` between
     `discount_amount_currency` and the move line's full residual (FR-2).
   - `@api.onchange("amount_currency")` — if the new value doesn't match
     `discount_amount_currency` while `pay_with_discount` is set, clear the flag (edge
     case 5). Guard against the onchange's own writes re-triggering itself.
   - Override `_prepare_account_payment_vals()` (FR-5): after building the existing
     dict, if any line in `self` has `pay_with_discount`, add
     `"write_off_line_vals": epd_adapter._epd_get_write_off_vals(self.filtered("pay_with_discount").mapped("move_line_id"))`.
6. **Views** (`views/account_payment_order.xml`): inherit the `account.payment.line`
   tree/form views shipped by `account_payment_order`; add `pay_with_discount`
   (`widget="boolean_toggle"`), `discount_date`; `decoration-success="pay_with_discount"`,
   `decoration-warning="discount_expiring"` on the tree view. No changes to the order
   form itself (chatter already renders `message_post` output).
7. **Readme fragments** per §9 (`DESCRIPTION.md` = spec §1 condensed, `CONFIGURE.md` =
   "no configuration; behavior is unconditional in v1", `USAGE.md` = short walkthrough,
   `ROADMAP.md` mentioning SDD support / multi-stage discounts / `bank-payment-alternative`
   port per spec, `CONTRIBUTORS.md` listing the author). `README.rst` is generated by
   `oca-gen-addon-readme` via pre-commit, not hand-edited.
8. **Tests** (`tests/test_epd_payment_order.py`, single `TransactionCase` fixture class
   per §10): implement T1–T12 in the order given (T8 — write-off equals Register
   Payment — early, since it's the correctness anchor per §12 step 6). T13 (SEPA CT) is
   a separate `@tagged` class with a runtime skip
   (`self.skipTest(...)` / class-level check) if `account_banking_sepa_credit_transfer`
   is not installed in the test database — not a hard `depends`.
9. **Local verification**:
   - Create a scratch database, install `account_payment_order` +
     `account_payment_order_early_payment_discount` (`account_banking_sepa_credit_transfer`
     included to also exercise T13), run with `--test-enable --test-tags
     /account_payment_order_early_payment_discount --stop-after-init`.
   - Separately re-run the existing `account_payment_order` test suite unmodified to
     confirm no regression (acceptance criterion in §13).
   - Drop the scratch database afterwards.
10. **`pre-commit run --files <new files>`** (black, isort, flake8, pylint-odoo,
    prettier on the new XML) — scoped to the new module only.
11. Grep-verify the acceptance-criteria constraint: no occurrence of
    `_is_eligible_for_early_payment_discount` or
    `_get_invoice_counterpart_amls_for_early_payment_discount` outside
    `models/epd_adapter.py`.

## 3. Explicitly not done in this pass

- No forward-port to 18.0/19.0.
- No RFC issue, no PR, no push to `origin` — implementation stays local until the user
  asks for it to go out.
- No `de.po` translation (marked optional in §9).
- No handling of `exchange_lines` in the adapter unless T12 (foreign currency) proves it
  necessary.

## 4. Acceptance criteria (from spec §13, unchanged)

- T1–T12 pass locally (T13 if SEPA CT module is present in the test DB); existing
  `account_payment_order` suite stays green.
- `pre-commit` clean on the new files.
- Grep proof holds (step 11 above).
- Module is additive: uninstalling it leaves `account_payment_order` functional as-is.

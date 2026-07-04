# Accounting Audit & Attestation

This document describes the audit-grade validation of the platform's accounting
subsystem and attests to its correctness. It covers **what** is validated, **how**
the checks are run, and the **result** of running them.

The platform keeps a single, double-entry **general ledger** (GL). Every
accounting feature — general journal, lease (ASC 842 / IFRS 16), accounts
receivable, accounts payable, CAM reconciliation, rent & security deposits, and
owner / trust accounting — records its economic events as *balanced* journal
entries in that one ledger. Because everything funnels through the GL, the whole
platform can be audited by re-deriving a small set of universal invariants over
the ledger and the statements built from it.

## Built-in auditor

`backend/app/services/accounting_audit_service.py` is an independent, read-only
auditor. It re-computes every invariant from the raw journal entries (it does
**not** trust the values cached on subledger records) and emits a structured
attestation report. It never mutates the ledger.

Run it programmatically:

```python
from app.services import accounting_audit_service as audit
report = await audit.run_audit(db, organization_id)
assert report["attested"] is True
```

…or over HTTP (finance roles — `admin` / `accountant`):

```
GET /api/v1/financials/audit-report
```

`attested` is `true` only when **every** check passes.

## Audit checks

| # | Check key | Category | What it proves |
|---|-----------|----------|----------------|
| 1 | `journal_entry_balance` | double-entry | Every journal entry balances (Σ debits = Σ credits). |
| 2 | `line_integrity` | double-entry | No line carries both a debit and a credit or a negative amount; every entry has ≥ 2 lines. |
| 3 | `account_scope_integrity` | isolation | Every line references an account owned by the entry's organization (no cross-tenant leakage). |
| 4 | `period_integrity` | periods | Every entry is filed in the accounting period matching its date. |
| 5 | `audit_trail_integrity` | audit trail | Every entry is `posted`, carries a provenance `source` tag, and has a `posted_at` timestamp. |
| 6 | `trial_balance` | double-entry | The ledger as a whole balances (a valid trial balance). |
| 7 | `control_account_integrity` | control accounts | Each subledger control account is only moved by its own authorised posting sources. |
| 8 | `accounting_equation` | statements | The balance sheet balances: Assets = Liabilities + Equity. |
| 9 | `net_income_tie` | statements | Income-statement net income ties to the balance sheet. |
| 10 | `cash_flow_tie` | statements | Cash-flow ending cash ties to the balance sheet's cash. |

### Control-account attestation

Each subledger posts to a dedicated GL *control* account. The auditor asserts
that a control account can **only** be moved by its own authorised posting
sources (plus `manual` opening balances), so a control balance can never be
silently contaminated by an unrelated entry:

| Account | Code | Authorised sources |
|---------|------|--------------------|
| Accounts Receivable | 1100 | `ar`, `rent`, `rent_late_fee` |
| CAM Receivable | 1200 | `cam` |
| CAM Refund Payable | 2100 | `cam` |
| Trust Cash | 1050 | `owner` |
| Accounts Payable | 2200 | `ap` |
| Security Deposits Held | 2300 | `deposit` |
| Due to Owners | 2500 | `owner` |

## Test coverage

The audit-level test suite `backend/tests/test_accounting_audit.py` exercises
all subsystems together through one ledger and then:

* **attests a healthy ledger** — a fixture posts manual, lease, AR (invoice +
  partial receipt), AP (bill + payment), owner (income + distribution), security
  deposit and CAM entries, then asserts the report is fully attested;
* **verifies invariants** — trial balance ties out, every entry balances,
  statements cross-tie, control accounts are clean, postings are idempotent
  (re-posting never double-counts), and organizations are isolated;
* **detects every class of corruption** — the suite injects an unbalanced entry,
  a dual-sided line, a single-line entry, a mis-filed period, a missing audit
  trail, a contaminated control account, and a cross-organization account, and
  asserts the auditor flags each one; and
* **covers the API** — the `/financials/audit-report` endpoint attests a clean
  ledger, flags a corrupt one, and is forbidden to non-finance roles.

Combined with the pre-existing per-feature suites (`test_gl`, `test_ar`,
`test_ap`, `test_cam`, `test_rent`, `test_owners`, `test_financials`,
`test_bank`, `test_billing_ledger`, `test_budgets`, `test_tax`), the accounting
surface is validated end to end.

Run the accounting suites:

```bash
cd backend
export POSTGRES_HOST=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
       JWT_SECRET=dev DEFAULT_ADMIN_PASSWORD=dev
# pytest-asyncio 0.21.2 is required for the session-scoped event loop fixture.
pytest tests/test_accounting_audit.py tests/test_gl.py tests/test_ar.py \
       tests/test_ap.py tests/test_cam.py tests/test_owners.py tests/test_rent.py \
       tests/test_financials.py tests/test_bank.py tests/test_billing_ledger.py \
       tests/test_budgets.py tests/test_tax.py
```

## Attestation

Running the auditor against a representative ledger spanning every subsystem
(manual opening balance, an ASC 842 lease schedule, AR, AP, owner trust, a
security deposit and a CAM true-up) produces:

```json
{
  "attested": true,
  "entry_count": 22,
  "total_debits": "93176.36",
  "total_credits": "93176.36",
  "checks_total": 10,
  "checks_passed": 10,
  "checks_failed": 0,
  "statement_summary": {
    "total_assets": "41500.00",
    "total_liabilities": "2800.00",
    "total_equity": "38700.00",
    "net_income": "-11300.00",
    "ending_cash": "40500.00"
  }
}
```

All 10 checks pass, the trial balance ties out to the cent, and the three
financial statements cross-tie. The full accounting test suite (per-feature +
audit-level) passes.

**Attested: the accounting subsystem produces balanced, traceable,
statement-consistent double-entry books.**

# Importing historical lease financials

An organization onboarding an existing tenancy rarely starts from a blank lease.
It typically arrives with eight years of prior leases, amendments and CAM
reconciliation statements, and wants that history in the system — without
disturbing the numbers the current lease is actually billing.

This feature imports those prior years into the lease's **CAM schedule** as
`historical` rows. It is deliberately a three-step pipeline — **parse → review →
import** — and the import step is the only one that writes anything.

## The invariant

> Importing history never changes the active lease's financial terms.

`Lease.payment_amount`, `Lease.payment_frequency`,
`Lease.annual_escalation_rate` and the rest of the lease's live financial
columns are untouched by every import path. The active lease remains the single
source of truth for the current period. The **only** way a schedule row's
figures reach the lease is the explicit `promote` action described below, which
is a separate, audited user action.

`backend/tests/test_cam_history.py::test_import_never_changes_lease_financials`
locks this in.

## What a schedule row holds

`lease_cam_entries` describes one lease-year. Beyond the CAM charge itself
(`amount`, or `percent_increase` relative to the prior year) a row carries:

| Group | Columns |
| --- | --- |
| Period | `year`, `period_start`, `period_end`, `period_status` (`historical` / `current` / `projected`) |
| Financials | `base_rent_amount`, `base_rent_frequency`, `base_rent_escalation_rate`, `operating_expense_amount`, `cam_psf`, `reconciliation_true_up` |
| Provenance | `source` (`manual` / `ai_import` / `csv_import` / `reconciliation`), `source_document_id`, `import_batch_id`, `extraction_confidence`, `review_status`, `imported_at` |

`period_start`/`period_end` exist because lease years are frequently
off-calendar or partial; when they are absent a row is treated as covering its
whole calendar year.

## Bulk-importing eight years of history

### 1. Parse (no database writes)

| Source | Endpoint |
| --- | --- |
| Lease / amendment / reconciliation PDF | `POST /api/v1/ai/leases/parse-history` (all tiers, same gating and 75 MB ceiling as `/ai/leases/parse`) |
| Spreadsheet export | `POST /api/v1/leases/{lease_id}/cam-entries/parse-csv` (max 2 MB) |

Both return the same shape — a list of proposed rows with per-row
`extraction_confidence`, plus the period the document appears to cover and any
warnings. Nothing is persisted.

CSV headers are matched against the same alias table the AI extractor uses, so
`Year, Base Rent, CAM, Escalation %` and
`year,base_rent_amount,amount,base_rent_escalation_rate` both work. Values may
arrive as `$12,500.50`, `3%` or `(450.00)` (an accounting-style credit) and are
normalized on the way in.

Large documents are split into segments before being sent to the model. A rent
schedule that spans several segments is merged **by year**, so a table broken
across pages arrives complete rather than being replaced by the last segment.

### 2. Review

The proposed rows are shown in an editable table with per-row include/exclude
and confidence badges. Rows whose period overlaps the active lease term are
highlighted: importing them as history is almost always a mis-scoped document
(the current lease re-imported as history).

### 3. Import

```
POST /api/v1/leases/{lease_id}/cam-entries/import      (admin | editor)
```

```jsonc
{
  "rows": [ /* the reviewed rows */ ],
  "mode": "skip_existing",          // skip_existing | overwrite | append
  "period_status": "historical",    // or "auto" to derive from each row's year
  "source": "ai_import",
  "source_document_id": null,
  "allow_active_period_overlap": false,
  "apply_to_lease": false           // only false is accepted
}
```

* Rows are deduplicated on `(lease_id, year, period_status)`. `mode` decides
  what happens when that key already exists: keep the existing row, overwrite
  its values, or add another row alongside it. Re-running the same import with
  the default `skip_existing` is therefore a no-op.
* Rows overlapping the active lease term come back as `conflict` results and are
  not written unless `allow_active_period_overlap` is `true`.
* `apply_to_lease: true` is rejected with `400`. The field exists so the intent
  is explicit and auditable.
* Every row written in one call shares an `import_batch_id`.

The response reports `created` / `updated` / `skipped` / `conflicts` counts plus
a per-row result carrying the reason for anything that was not written.

### Reverting a bad import

```
DELETE /api/v1/leases/{lease_id}/cam-entries/import/{batch_id}
```

Deletes every row written by that batch. Multi-document imports that were posted
as one call share a batch, so a whole onboarding pass can be undone at once.

### Promoting a row to the current terms

```
POST /api/v1/leases/{lease_id}/cam-entries/{entry_id}/promote
```

Copies the row's `base_rent_amount` / `base_rent_frequency` /
`base_rent_escalation_rate` onto the lease's live `payment_amount` /
`payment_frequency` / `annual_escalation_rate`, and records the before/after in
the activity log. This is the only path from a schedule row to the active
lease's financials, and it is never taken automatically.

## How historical rows behave downstream

* **Escalation chain** — a `percent_increase` row grows the prior year's
  resolved charge *within its own period group*. Historical rows chain among
  themselves; the current/projected rows form a separate chain. Importing eight
  years of history can never re-base what the active lease is billing today.
  The resolved figure is exposed as `effective_amount` on each row.
* **Billing / GL / AR** — historical rows are reference data. Nothing generates
  charges, GL postings or receivables from them.
* **CAM reconciliation review** — `POST /cam/reconciliations/{id}/ai-review`
  passes the lease's historical rows to the model as prior-year comparatives, so
  the reviewer has a real multi-year baseline instead of only the single prior
  reconciliation statement stored in the system.
* **Knowledge / RAG** — `lease_cam_entries` is covered by the generic org-scoped
  indexer, so imported history is searchable through the portfolio assistant
  without any bespoke wiring.

## Schema notes

Migration `109_add_cam_history_columns` adds the columns above; it is
inspector-guarded and safe to re-run. Long-lived databases that were
`create_all`-stamped at head also self-heal through
`backend/start.py::_RECONCILE_COLUMNS`.

There is deliberately **no** database unique constraint on
`(lease_id, year, period_status)`: existing deployments may already hold several
rows for one lease-year, which would make such a constraint fail to apply.
Uniqueness is enforced by the import service instead.

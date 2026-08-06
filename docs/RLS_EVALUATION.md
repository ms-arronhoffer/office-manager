# Row-Level Security (RLS) Evaluation — Defense-in-Depth Backstop

**Status:** Production-enabled defense-in-depth backstop (revision 118).
**Scope:** P1.5 — "Evaluate Postgres Row-Level Security as a defense-in-depth
backstop (set `app.current_org` per request), so a missed filter fails
closed."

## Why

The application already scopes almost every per-org resource lookup at the
ORM/query layer (see `docs/TENANT_SCOPING.md` / `app/utils/tenant_scope.py`
and the CI lint that forbids unscoped primary-key lookups). That is a
**structural** control: it depends on every router remembering to apply it.
RLS adds an **orthogonal, database-enforced** control: even if a query
forgets the `organization_id` filter, Postgres itself will not return rows
belonging to another tenant. Two independent layers mean a single missed
filter degrades to "no rows" instead of "cross-tenant data leak."

## Design

1. **Session context:** `app/utils/rls.py::set_session_org()` issues
   `SET LOCAL app.current_org = '<uuid>'` on the current transaction whenever
   the app resolves an authenticated user's organization
   (`get_current_user`, `get_current_org`, `enforce_org_access` in
   `app/auth/dependencies.py`). `SET LOCAL` is transaction-scoped, so it can
   never leak across requests that reuse a pooled connection.
2. **Policy:** Revision `118` uses both `USING` and `WITH CHECK` with
   `organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid`.
   Missing/empty context therefore returns no protected rows and rejects
   inserts/updates. `ENABLE` plus `FORCE ROW LEVEL SECURITY` applies this to
   table owners as well as ordinary roles.
3. **Trusted bypass:** `app.rls_bypass='on'` is a separate transaction-local
   mode. Only backend-controlled platform identities, opaque portal-token
   resolution, and audited scheduler entry points set it. Request parameters,
   headers and token claims can never select bypass. Tenant context explicitly
   sets bypass back to `off`.
4. **Feature flag:** production Compose defaults `RLS_BACKSTOP_ENABLED=true`;
   local Compose defaults it to `false`. The database policy is independent of
   the flag, so any local database migrated to `118` must enable the flag when
   exercising protected application paths.

## Coverage in revision 118

The explicit allowlist is: `leases`, `customers`, `customer_invoices`,
`customer_receipts`, `vendor_bills`, `vendor_payments`, `gl_accounts`,
`accounting_periods`, `journal_entries`, `bank_accounts`, `bank_transactions`,
`bank_reconciliations`, `budgets`, `operating_expenses`, `rent_charges`,
`security_deposits`, `residents`, `resident_leases`,
`resident_payment_methods`, `client_portal_accounts`,
`client_portal_change_requests`, and `rental_units`.

All have a direct `organization_id`. Child tables that only inherit tenancy
through a parent are intentionally not covered: `customer_invoice_lines`,
`vendor_bill_lines`, `journal_entry_lines`, `budget_lines`,
`cam_reconciliation_lines`, and `resident_lease_occupants`. Parent-join RLS
for those tables needs separate query-plan and cascade testing. Other lower-risk
org-scoped domains remain protected by ORM scoping and tenant lint, not RLS.

Scheduler paths that reach protected tables use transaction-local system bypass
(`lease_reminders`, `weekly_summary`, and `scheduled_reports`). Knowledge
indexing sets tenant context separately for each organization and re-establishes
it after service commits. Public client/owner/resident portal flows use bypass
only to resolve an opaque portal or signup token, then immediately switch to the
resolved account's tenant context.

## Threat model

The bypass protects application availability; it is not a privilege boundary
against SQL injection or a compromised backend process, because any principal
that can execute arbitrary SQL on the application connection can call
`set_config`. The application DB role must not have `SUPERUSER` or `BYPASSRLS`;
Postgres superusers bypass RLS even with `FORCE`. Keep direct database access and
the migration role separately controlled. Application-level org predicates
remain mandatory.

## Rollout and rollback

1. Deploy code with the context helpers and migration `118`; container startup
   runs `alembic upgrade head` before starting the API. Fresh/create-all schemas
   stamp at `117` and then execute `118` rather than stamping over the policies.
2. Production Compose enables `RLS_BACKSTOP_ENABLED`; monitor empty-result and
   policy-denial errors, portal authentication, reminders, reports and indexing.
3. To stop request context setting while investigating, set the flag false only
   after rolling the database back. `alembic downgrade 117` removes revision-118
   policies and restores the revision-090 fail-open lease pilot policy.
4. Add future tables only after auditing request, platform, public and background
   access paths and adding a database-role enforcement test.

## What NOT to do

Do not blanket-enable RLS across every org-scoped table in one migration.
The blast radius of a misconfigured policy (empty result sets returned as
"success" rather than an error) is worse than the IDOR risk it mitigates,
because it fails silently. Roll out table-by-table per the plan above.

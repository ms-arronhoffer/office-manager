# Row-Level Security (RLS) Evaluation — Defense-in-Depth Backstop

**Status:** Evaluated and piloted (opt-in, disabled by default).
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
2. **Policy:** For each opted-in table, a `CREATE POLICY ... USING
   (organization_id = current_setting('app.current_org', true)::uuid)` plus
   `ENABLE`/`FORCE ROW LEVEL SECURITY` makes Postgres itself refuse rows
   outside the caller's org — including for superuser-owned connections
   using `FORCE`, and for any query shape (raw SQL, ORM, admin scripts).
3. **Fail mode during rollout:** the pilot policy (see migration `090`) also
   permits rows when `app.current_org` is unset, so tables/paths that haven't
   been updated to set the GUC yet (background jobs, `psql`, alembic) are
   unaffected. This is intentionally **fail-open only when no context is set
   at all**, and **fail-closed the instant a context is set but doesn't
   match** — i.e. exactly the "app-level filter was missed" scenario this
   feature targets, without breaking not-yet-migrated code paths.
4. **Feature flag:** `settings.RLS_BACKSTOP_ENABLED` (default `False`) gates
   whether the app sets the GUC at all; the DB-side policy is independent of
   the flag (once migration `090` is applied, the policy exists and behaves
   per the fail-mode above regardless of the flag — the flag only controls
   whether *this app* participates by setting its own context).

## Why only one pilot table today

Several org-scoped tables are also written by **background jobs** that run
outside any HTTP request (`app/tasks/recurring_tickets.py`,
`app/tasks/audit_log_pruning.py`, and others under `app/tasks/`). Those jobs
iterate across all organizations in a single DB session and do not currently
set `app.current_org` per org before touching each org's rows. Enabling
`FORCE ROW LEVEL SECURITY` on tables those jobs touch would silently drop
their writes/reads once a session context happens to be set by an unrelated
concurrent request on a pooled connection, or would require every background
job to also set/reset the GUC per org iteration.

`leases` was chosen as the pilot table because it has no background-job
dependency (verified by grepping `app/tasks/` for the model) and is
exclusively read/written through HTTP-request-scoped routers that already go
through `get_current_user`/`get_current_org`.

## Rollout plan (recommended follow-up, not yet executed)

1. Run the `leases` pilot in a staging environment with
   `RLS_BACKSTOP_ENABLED=true`, monitor for unexpected empty-result
   regressions (would indicate a code path reads leases without going
   through the auth dependency chain, e.g. a Celery/cron task added later).
2. Update `app/tasks/*` background jobs to explicitly `SET LOCAL
   app.current_org` (or use `SET app.current_org` + reset) per org inside
   their iteration loop before touching org-scoped tables.
3. Extend the same migration pattern (`ENABLE`/`FORCE ROW LEVEL SECURITY` +
   policy) to the next tier of tables, prioritizing by sensitivity: financial
   tables (`customer_invoices`, `vendor_bills`, GL tables) before lower-risk
   ones.
4. Once all read paths for a table reliably set the GUC, tighten that
   table's policy to drop the "unset context = allow" clause, making it
   fail-closed unconditionally (matching the literal ask in P1.5).
5. Consider a dedicated, lower-privilege Postgres role for the app connection
   (distinct from the migration/superuser role) so `FORCE ROW LEVEL SECURITY`
   can't be silently bypassed by a future migration that connects as a
   table-owner role — today the app and alembic share `POSTGRES_USER`, which
   works with `FORCE ROW LEVEL SECURITY` but is worth revisiting.

## What NOT to do

Do not blanket-enable RLS across every org-scoped table in one migration.
The blast radius of a misconfigured policy (empty result sets returned as
"success" rather than an error) is worse than the IDOR risk it mitigates,
because it fails silently. Roll out table-by-table per the plan above.

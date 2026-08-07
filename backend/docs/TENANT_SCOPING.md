# Tenant scoping convention

Always use `load_or_404` and `scoped` from `app.utils.tenant_scope` for any per-organization resource lookup by primary key.

Never write a bare `select(Model).where(Model.id == ...)` in routers without an org filter. The `backend/scripts/check_tenant_scoping.py` CI lint enforces this rule.

`backend/tests/test_cross_tenant_isolation.py` is the regression guardrail for cross-tenant access: foreign-tenant IDs must return 404, never leak data.

## PostgreSQL RLS backstop

Revision `118` adds fail-closed PostgreSQL RLS to the audited high-risk direct-org
tables listed in `docs/RLS_EVALUATION.md`. Authenticated tenant requests set
`app.current_org` with transaction-local `set_config`; missing context sees no
protected rows, and `WITH CHECK` rejects cross-tenant writes. API keys use the
same context path as JWT users.

Trusted system/platform operations use transaction-local `app.rls_bypass='on'`.
Never derive bypass from request input. Portal token lookup is the only public
pre-tenant use: after resolving the opaque token, code must immediately call
`set_session_org`. A commit or rollback clears both local settings, so a path
that continues querying afterward must establish context again.

RLS is defense in depth, not a replacement for `scoped`, `load_or_404`, explicit
org predicates, or tenant lint. The application database role must not be a
Postgres superuser and must not have `BYPASSRLS`.

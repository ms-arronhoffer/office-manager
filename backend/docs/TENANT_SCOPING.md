# Tenant scoping convention

Always use `load_or_404` and `scoped` from `app.utils.tenant_scope` for any per-organization resource lookup by primary key.

Never write a bare `select(Model).where(Model.id == ...)` in routers without an org filter. The `backend/scripts/check_tenant_scoping.py` CI lint enforces this rule.

`backend/tests/test_cross_tenant_isolation.py` is the regression guardrail for cross-tenant access: foreign-tenant IDs must return 404, never leak data.

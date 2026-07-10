"""Row-Level Security backstop pilot on the leases table

Revision ID: 090
Revises: 081
Create Date: 2026-07-10

This migration is the implementation half of the "evaluate Postgres RLS as a
defense-in-depth backstop" item in docs/RLS_EVALUATION.md. It is intentionally
scoped to a single, low-risk, purely request-driven table (`leases`) as a
pilot rather than a blanket rollout, because:

  * Some org-scoped tables are also read/written by background jobs that run
    outside an HTTP request (see backend/app/tasks/*), which do not currently
    set the `app.current_org` session GUC. Enabling RLS on those tables first
    would break those jobs (fail-closed also means "closed" to legitimate
    background writers that haven't been updated yet).
  * `leases` has no such background-job dependency (verified via grep of
    backend/app/tasks/), making it a safe first table to validate the
    approach against real traffic before expanding coverage.

Rollout is opt-in and reversible:
  * The policy only *rejects* rows once `RLS_BACKSTOP_ENABLED=true` is also
    set in the app config AND this migration has been applied — until this
    migration is run, RLS is not enabled at all, so there is zero behavior
    change by default.
  * The policy always permits the row when `app.current_org` is unset (empty
    string) so a plain `psql` session, alembic itself, or a not-yet-updated
    background job still works exactly as before; only requests attempting a
    cross-org access will actually get filtered, because app code always
    scopes its own queries by organization_id first — the RLS policy is a
    second, independent gate that fails closed *specifically* when a query
    forgets the app-level filter but a session context *is* set (i.e. exactly
    the "missed filter" scenario this is meant to catch).

To move from "fail-open when GUC unset" to a stricter "fail-closed always",
flip the policy's `current_setting('app.current_org', true) = ''` clause off
once every code path that touches `leases` is confirmed to always set the
GUC (i.e. once background jobs are updated too).
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "090"
down_revision = "081"
branch_labels = None
depends_on = None

_POLICY_NAME = "leases_org_isolation"


def upgrade() -> None:
    op.execute("ALTER TABLE leases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leases FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {_POLICY_NAME} ON leases
        USING (
            current_setting('app.current_org', true) IS NULL
            OR current_setting('app.current_org', true) = ''
            OR organization_id = current_setting('app.current_org', true)::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON leases")
    op.execute("ALTER TABLE leases NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leases DISABLE ROW LEVEL SECURITY")

"""Row-Level Security (RLS) session-context helper.

This module implements the "set app.current_org per request" half of the RLS
defense-in-depth backstop described in docs/RLS_EVALUATION.md. It is safe to
call unconditionally: setting a Postgres session GUC has no effect unless a
table has an RLS policy that reads it, so wiring this into the auth
dependency chain does not change behavior until (a) `settings.RLS_BACKSTOP_ENABLED`
is true and (b) the corresponding alembic migration has enabled RLS + a
policy on a given table.

Why `SET LOCAL` and not a session-level `SET`: the app uses a pooled asyncpg
connection per request (see app/database.py). `SET LOCAL` scopes the setting
to the current transaction and is automatically reset when the transaction
ends, so a connection returned to the pool never leaks one request's org
context into the next request that happens to reuse the same physical
connection.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


async def set_session_org(db: AsyncSession, organization_id: uuid.UUID | None) -> None:
    """Set the `app.current_org` GUC for the current transaction.

    No-op unless `RLS_BACKSTOP_ENABLED` is set and an organization_id is known
    (super-admins / org-less users are intentionally left unset — RLS
    policies should be written to also allow a bypass role for platform
    admin tooling; see docs/RLS_EVALUATION.md).
    """
    if not settings.RLS_BACKSTOP_ENABLED or organization_id is None:
        return
    # Must run inside a transaction for SET LOCAL to take effect; SQLAlchemy's
    # AsyncSession begins one implicitly on first statement execution.
    await db.execute(text("SET LOCAL app.current_org = :org"), {"org": str(organization_id)})

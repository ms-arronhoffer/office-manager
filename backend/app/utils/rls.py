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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


async def set_session_org(db: AsyncSession, organization_id: uuid.UUID | None) -> None:
    """Set the `app.current_org` GUC for the current transaction.

    No-op unless `RLS_BACKSTOP_ENABLED` is set and an organization_id is known.
    Database-confirmed super-admins use the separate trusted bypass helper.
    """
    if not settings.RLS_BACKSTOP_ENABLED or organization_id is None:
        return
    await _set_tenant_context(db, organization_id)


async def _set_tenant_context(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Apply fail-closed tenant context to the current transaction."""
    await db.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(organization_id)},
    )
    await db.execute(text("SELECT set_config('app.rls_bypass', 'off', true)"))


async def set_system_bypass(db: AsyncSession) -> None:
    """Enable the trusted system/platform RLS bypass for this transaction.

    Callers must derive this decision from backend-controlled execution state,
    never from a request parameter, header, token claim, or other user input.
    """
    if not settings.RLS_BACKSTOP_ENABLED:
        return
    await db.execute(text("SELECT set_config('app.current_org', '', true)"))
    await db.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))


@asynccontextmanager
async def tenant_context(
    db: AsyncSession, organization_id: uuid.UUID
) -> AsyncIterator[None]:
    """Set transaction-local tenant context around a trusted backend operation."""
    if settings.RLS_BACKSTOP_ENABLED:
        await _set_tenant_context(db, organization_id)
    yield


@asynccontextmanager
async def system_bypass(db: AsyncSession) -> AsyncIterator[None]:
    """Set transaction-local bypass around a narrow trusted backend operation."""
    await set_system_bypass(db)
    yield

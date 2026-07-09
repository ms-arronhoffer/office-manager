"""Buildium migration connector API — ``/api/v1/buildium``.

Admin-only, org-scoped endpoints backing the Administration › System & Data ›
"Buildium Migration" page: connection configuration, GL-account mapping, and
starting/polling a migration run.

Long-running migration work executes via a FastAPI ``BackgroundTasks`` job
guarded by a Postgres advisory lock (mirroring ``app.tasks.job_status``) so at
most one migration runs per organization at a time; progress is persisted on
:class:`~app.models.buildium.BuildiumMigrationRun` and polled by the UI.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import async_session, engine, get_db
from app.models.buildium import (
    BUILDIUM_ENTITY_TYPES,
    BuildiumConnection,
    BuildiumEntityMap,
    BuildiumGLAccountMap,
    BuildiumMigrationRun,
)
from app.models.general_ledger import GLAccount
from app.models.user import User
from app.services.buildium.client import BuildiumApiError, BuildiumClient
from app.services.buildium.migration_service import ENTITY_STEPS, run_migration
from app.utils.crypto import decrypt_secret, encrypt_secret, mask_secret

logger = logging.getLogger(__name__)

router = APIRouter()

Admin = require_role("admin")


def _advisory_key(organization_id: uuid.UUID) -> int:
    import hashlib
    digest = hashlib.sha256(f"buildium-migration:{organization_id}".encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def _require_org(current_user: User) -> uuid.UUID:
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    return current_user.organization_id


# ─── Schemas ───────────────────────────────────────────────────────────────

class ConnectionOut(BaseModel):
    configured: bool
    client_id: str | None = None
    client_secret_hint: str | None = None
    base_url: str | None = None
    is_enabled: bool = True
    last_verified_at: datetime | None = None
    last_verify_ok: bool | None = None
    last_verify_error: str | None = None
    last_sync_at: datetime | None = None
    last_sync_summary: dict | None = None


class ConnectionIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1)
    base_url: str | None = None
    is_enabled: bool = True


class TestConnectionOut(BaseModel):
    ok: bool
    error: str | None = None


class GLAccountMapOut(BaseModel):
    id: uuid.UUID
    buildium_gl_account_id: str
    buildium_account_name: str | None
    buildium_account_type: str | None
    gl_account_id: uuid.UUID | None
    gl_account_name: str | None = None
    auto_created: bool


class GLAccountMapUpdate(BaseModel):
    gl_account_id: uuid.UUID


class MigrateRequest(BaseModel):
    entities: list[str] | None = None
    dry_run: bool = False


class MigrationRunOut(BaseModel):
    id: uuid.UUID
    status: str
    dry_run: bool
    requested_entities: list | None
    progress: dict
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


def _run_to_out(run: BuildiumMigrationRun) -> MigrationRunOut:
    return MigrationRunOut(
        id=run.id, status=run.status, dry_run=run.dry_run,
        requested_entities=run.requested_entities, progress=run.progress or {},
        error_message=run.error_message, started_at=run.started_at,
        finished_at=run.finished_at, created_at=run.created_at,
    )


async def _get_connection(db: AsyncSession, organization_id: uuid.UUID) -> BuildiumConnection | None:
    return (
        await db.execute(
            select(BuildiumConnection).where(BuildiumConnection.organization_id == organization_id)
        )
    ).scalar_one_or_none()


async def _require_connection(db: AsyncSession, organization_id: uuid.UUID) -> BuildiumConnection:
    conn = await _get_connection(db, organization_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Buildium connection is not configured. Save a client id/secret first.",
        )
    return conn


def _build_client(conn: BuildiumConnection) -> BuildiumClient:
    return BuildiumClient(
        client_id=conn.client_id,
        client_secret=decrypt_secret(conn.client_secret_encrypted),
        base_url=conn.base_url,
    )


# ─── Connection ────────────────────────────────────────────────────────────

@router.get("/connection", response_model=ConnectionOut)
async def get_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    conn = await _get_connection(db, org_id)
    if conn is None:
        return ConnectionOut(configured=False)
    return ConnectionOut(
        configured=True,
        client_id=conn.client_id,
        client_secret_hint=mask_secret(decrypt_secret(conn.client_secret_encrypted)),
        base_url=conn.base_url,
        is_enabled=conn.is_enabled,
        last_verified_at=conn.last_verified_at,
        last_verify_ok=conn.last_verify_ok,
        last_verify_error=conn.last_verify_error,
        last_sync_at=conn.last_sync_at,
        last_sync_summary=conn.last_sync_summary,
    )


@router.put("/connection", response_model=ConnectionOut)
async def save_connection(
    payload: ConnectionIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    conn = await _get_connection(db, org_id)
    if conn is None:
        conn = BuildiumConnection(organization_id=org_id, client_id=payload.client_id,
                                   client_secret_encrypted=encrypt_secret(payload.client_secret))
        db.add(conn)
    conn.client_id = payload.client_id
    conn.client_secret_encrypted = encrypt_secret(payload.client_secret)
    if payload.base_url:
        conn.base_url = payload.base_url
    conn.is_enabled = payload.is_enabled
    # Credentials changed — clear any stale verification state.
    conn.last_verified_at = None
    conn.last_verify_ok = None
    conn.last_verify_error = None
    await db.commit()
    await db.refresh(conn)
    return await get_connection(db=db, current_user=current_user)


@router.post("/connection/test", response_model=TestConnectionOut)
async def test_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    conn = await _require_connection(db, org_id)
    client = _build_client(conn)
    ok, error = await client.test_connection()
    conn.last_verified_at = datetime.now(timezone.utc)
    conn.last_verify_ok = ok
    conn.last_verify_error = error
    await db.commit()
    return TestConnectionOut(ok=ok, error=error)


# ─── GL account mapping ────────────────────────────────────────────────────

@router.get("/gl-mapping", response_model=list[GLAccountMapOut])
async def list_gl_mapping(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    rows = (
        await db.execute(
            select(BuildiumGLAccountMap, GLAccount)
            .outerjoin(GLAccount, BuildiumGLAccountMap.gl_account_id == GLAccount.id)
            .where(BuildiumGLAccountMap.organization_id == org_id)
            .order_by(BuildiumGLAccountMap.buildium_account_name)
        )
    ).all()
    out: list[GLAccountMapOut] = []
    for mapping, gl_account in rows:
        out.append(
            GLAccountMapOut(
                id=mapping.id,
                buildium_gl_account_id=mapping.buildium_gl_account_id,
                buildium_account_name=mapping.buildium_account_name,
                buildium_account_type=mapping.buildium_account_type,
                gl_account_id=mapping.gl_account_id,
                gl_account_name=gl_account.name if gl_account else None,
                auto_created=mapping.auto_created,
            )
        )
    return out


@router.put("/gl-mapping/{mapping_id}", response_model=GLAccountMapOut)
async def update_gl_mapping(
    mapping_id: uuid.UUID,
    payload: GLAccountMapUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    mapping = await db.get(BuildiumGLAccountMap, mapping_id)
    if mapping is None or mapping.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    account = await db.get(GLAccount, payload.gl_account_id)
    if account is None or account.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown GL account")
    mapping.gl_account_id = payload.gl_account_id
    mapping.auto_created = False
    await db.commit()
    await db.refresh(mapping)
    return GLAccountMapOut(
        id=mapping.id, buildium_gl_account_id=mapping.buildium_gl_account_id,
        buildium_account_name=mapping.buildium_account_name,
        buildium_account_type=mapping.buildium_account_type,
        gl_account_id=mapping.gl_account_id, gl_account_name=account.name,
        auto_created=mapping.auto_created,
    )


# ─── Migration runs ─────────────────────────────────────────────────────────

@router.get("/entities")
async def list_entity_types(current_user: User = Depends(Admin)):
    """The set of migratable entity types, in execution order, for the UI checklist."""
    return [{"key": key, "label": label} for key, label in ENTITY_STEPS]


async def _execute_run(run_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Background job body: executes a migration run to completion.

    Runs in its own DB session/connection (the request's session is closed by
    the time this executes) and is guarded by a Postgres advisory lock so a
    second "Start migration" click can't run concurrently for the same org.
    """
    key = _advisory_key(organization_id)
    async with engine.connect() as lock_raw_conn:
        lock_conn = await lock_raw_conn.execution_options(isolation_level="AUTOCOMMIT")
        got_lock = await lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})
        if not got_lock:
            async with async_session() as db:
                run = await db.get(BuildiumMigrationRun, run_id)
                if run:
                    run.status = "failed"
                    run.error_message = "Another migration is already running for this organization."
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
            return
        try:
            async with async_session() as db:
                run = await db.get(BuildiumMigrationRun, run_id)
                if run is None:
                    return
                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
                await db.commit()

                conn = await _get_connection(db, organization_id)
                if conn is None:
                    raise BuildiumApiError("Buildium connection is not configured.")
                client = _build_client(conn)

                async def _on_progress(entity_type: str, entity_progress: dict) -> None:
                    run.progress = {**(run.progress or {}), entity_type: entity_progress}
                    await db.commit()

                progress = await run_migration(
                    db, organization_id, client,
                    entities=run.requested_entities, dry_run=run.dry_run,
                    actor_id=run.started_by_id, on_progress=_on_progress,
                )
                any_errors = any(p.get("errors") for p in progress.values())
                run.status = "partial" if any_errors else "succeeded"
                run.finished_at = datetime.now(timezone.utc)
                if not run.dry_run:
                    conn.last_sync_at = run.finished_at
                    conn.last_sync_summary = progress
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Buildium migration run %s failed", run_id)
            async with async_session() as db:
                run = await db.get(BuildiumMigrationRun, run_id)
                if run:
                    run.status = "failed"
                    run.error_message = str(exc)
                    run.finished_at = datetime.now(timezone.utc)
                    await db.commit()
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})


@router.post("/migrate", response_model=MigrationRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_migration(
    payload: MigrateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    await _require_connection(db, org_id)

    if payload.entities:
        unknown = set(payload.entities) - set(BUILDIUM_ENTITY_TYPES)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown entity type(s): {', '.join(sorted(unknown))}",
            )

    # Only one active run per org at a time.
    active = (
        await db.execute(
            select(BuildiumMigrationRun).where(
                BuildiumMigrationRun.organization_id == org_id,
                BuildiumMigrationRun.status.in_(("pending", "running")),
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A migration run is already in progress for this organization.",
        )

    run = BuildiumMigrationRun(
        organization_id=org_id,
        status="pending",
        dry_run=payload.dry_run,
        requested_entities=payload.entities,
        progress={},
        started_by_id=current_user.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(_execute_run, run.id, org_id)
    return _run_to_out(run)


@router.get("/runs", response_model=list[MigrationRunOut])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    rows = (
        await db.execute(
            select(BuildiumMigrationRun)
            .where(BuildiumMigrationRun.organization_id == org_id)
            .order_by(BuildiumMigrationRun.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return [_run_to_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=MigrationRunOut)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    run = await db.get(BuildiumMigrationRun, run_id)
    if run is None or run.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration run not found")
    return _run_to_out(run)


@router.post("/runs/{run_id}/cancel", response_model=MigrationRunOut)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    """Mark a pending/running run cancelled. Best-effort: an in-flight batch
    already fetched from Buildium will finish that batch before the next
    ``on_progress`` checkpoint observes the cancellation."""
    org_id = _require_org(current_user)
    run = await db.get(BuildiumMigrationRun, run_id)
    if run is None or run.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration run not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run is not active")
    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()
    return _run_to_out(run)


# entity crosswalk count, useful for the UI's "already migrated" summary.
@router.get("/summary")
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = _require_org(current_user)
    rows = (
        await db.execute(
            select(BuildiumEntityMap.entity_type, BuildiumEntityMap.id)
            .where(BuildiumEntityMap.organization_id == org_id)
        )
    ).all()
    counts: dict[str, int] = {}
    for entity_type, _id in rows:
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return counts

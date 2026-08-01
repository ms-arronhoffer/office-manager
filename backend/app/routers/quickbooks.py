"""QuickBooks Online connector API — ``/api/v1/quickbooks``.

Live two-way sync with QuickBooks Online, replacing the CSV-only export in
``app.routers.gl``:

* OAuth2 authorization-code connect / disconnect (tokens encrypted at rest).
* Incremental push of posted journal entries as QBO ``JournalEntry`` objects.
* Pull of the QBO chart of accounts with auto-matching and manual override.

Finance staff only, and gated on the ``advanced_accounting`` entitlement (both
here and at router registration in ``app.main``). When the Intuit app
credentials are absent the endpoints report an unconfigured connector rather
than failing, mirroring the other optional integrations.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_feature, require_role
from app.database import get_db
from app.models.external_sync import QuickBooksAccountMap, QuickBooksConnection
from app.models.general_ledger import GLAccount
from app.models.user import User
from app.services.quickbooks import client as qbo_client
from app.services.quickbooks import sync_service as svc
from app.services.quickbooks.client import QuickBooksApiError

logger = logging.getLogger(__name__)

router = APIRouter()

# Finance staff only, and only on a plan that includes advanced accounting.
FinanceUser = require_role("admin", "accountant")
AdvancedAccounting = require_feature("advanced_accounting")


def _require_org(current_user: User) -> uuid.UUID:
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    return current_user.organization_id


async def _require_connection(
    db: AsyncSession, organization_id: uuid.UUID
) -> QuickBooksConnection:
    conn = await svc.get_connection(db, organization_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="QuickBooks is not connected. Start the connect flow first.",
        )
    return conn


# ─── Schemas ───────────────────────────────────────────────────────────────

class ConnectionOut(BaseModel):
    configured: bool
    connected: bool
    realm_id: str | None = None
    environment: str | None = None
    status: str | None = None
    last_sync_at: datetime | None = None
    last_sync_cursor: str | None = None
    last_error: str | None = None
    access_token_expires_at: datetime | None = None


class AuthorizeUrlOut(BaseModel):
    configured: bool
    authorize_url: str | None = None
    state: str | None = None
    detail: str | None = None


class CallbackIn(BaseModel):
    code: str = Field(min_length=1)
    realm_id: str = Field(min_length=1)
    state: str | None = None


class SyncRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)


class SyncResultOut(BaseModel):
    candidates: int = 0
    pushed: int = 0
    adopted: int = 0
    skipped: int = 0
    failed: int = 0
    cursor: str | None = None
    errors: list[str] = []


class AccountMapOut(BaseModel):
    id: uuid.UUID
    qbo_account_id: str
    qbo_account_name: str | None
    qbo_account_type: str | None
    qbo_account_number: str | None
    gl_account_id: uuid.UUID | None
    gl_account_name: str | None = None
    manual_override: bool


class AccountMapUpdate(BaseModel):
    gl_account_id: uuid.UUID | None = None


class PullAccountsOut(BaseModel):
    pulled: int
    created: int
    updated: int
    auto_matched: int


class SyncLogOut(BaseModel):
    id: uuid.UUID
    direction: str
    status: str
    cursor_before: str | None
    cursor_after: str | None
    counts: dict | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


def _connection_out(conn: QuickBooksConnection | None) -> ConnectionOut:
    configured = svc.is_configured()
    if conn is None:
        return ConnectionOut(configured=configured, connected=False)
    return ConnectionOut(
        configured=configured,
        connected=True,
        realm_id=conn.realm_id,
        environment=conn.environment,
        status=conn.status,
        last_sync_at=conn.last_sync_at,
        last_sync_cursor=conn.last_sync_cursor,
        last_error=conn.last_error,
        access_token_expires_at=conn.access_token_expires_at,
    )


# ─── Connection lifecycle ──────────────────────────────────────────────────

@router.get("/connection", response_model=ConnectionOut)
async def get_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    org_id = _require_org(current_user)
    return _connection_out(await svc.get_connection(db, org_id))


@router.get("/authorize-url", response_model=AuthorizeUrlOut)
async def get_authorize_url(
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    """Build the Intuit consent URL the admin's browser is sent to."""
    _require_org(current_user)
    if not svc.is_configured():
        return AuthorizeUrlOut(
            configured=False,
            detail="QuickBooks is not configured on this deployment.",
        )
    state = secrets.token_urlsafe(24)
    return AuthorizeUrlOut(
        configured=True, authorize_url=qbo_client.authorize_url(state), state=state
    )


@router.post("/callback", response_model=ConnectionOut)
async def oauth_callback(
    payload: CallbackIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    """Complete the authorization-code exchange and store the grant."""
    org_id = _require_org(current_user)
    if not svc.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="QuickBooks is not configured on this deployment.",
        )
    try:
        tokens = await qbo_client.exchange_code(payload.code)
    except QuickBooksApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    conn = await svc.store_connection(
        db, org_id, realm_id=payload.realm_id, tokens=tokens
    )
    return _connection_out(conn)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    org_id = _require_org(current_user)
    conn = await svc.get_connection(db, org_id)
    if conn is not None:
        await svc.disconnect(db, conn)


# ─── Chart of accounts ─────────────────────────────────────────────────────

@router.post("/accounts/pull", response_model=PullAccountsOut)
async def pull_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    org_id = _require_org(current_user)
    conn = await _require_connection(db, org_id)
    try:
        client = await svc.build_client(db, conn)
        result = await svc.pull_chart_of_accounts(db, org_id, client)
    except QuickBooksApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return PullAccountsOut(**result)


@router.get("/accounts", response_model=list[AccountMapOut])
async def list_account_mappings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    org_id = _require_org(current_user)
    rows = (
        await db.execute(
            select(QuickBooksAccountMap, GLAccount)
            .outerjoin(GLAccount, QuickBooksAccountMap.gl_account_id == GLAccount.id)
            .where(QuickBooksAccountMap.organization_id == org_id)
            .order_by(QuickBooksAccountMap.qbo_account_name)
        )
    ).all()
    return [
        AccountMapOut(
            id=mapping.id,
            qbo_account_id=mapping.qbo_account_id,
            qbo_account_name=mapping.qbo_account_name,
            qbo_account_type=mapping.qbo_account_type,
            qbo_account_number=mapping.qbo_account_number,
            gl_account_id=mapping.gl_account_id,
            gl_account_name=gl_account.name if gl_account else None,
            manual_override=mapping.manual_override,
        )
        for mapping, gl_account in rows
    ]


@router.put("/accounts/{mapping_id}", response_model=AccountMapOut)
async def update_account_mapping(
    mapping_id: uuid.UUID,
    payload: AccountMapUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    org_id = _require_org(current_user)
    mapping = await db.get(QuickBooksAccountMap, mapping_id)
    if mapping is None or mapping.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")

    account: GLAccount | None = None
    if payload.gl_account_id is not None:
        account = await db.get(GLAccount, payload.gl_account_id)
        if account is None or account.organization_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown GL account"
            )
    mapping.gl_account_id = payload.gl_account_id
    mapping.manual_override = payload.gl_account_id is not None
    await db.commit()
    await db.refresh(mapping)
    return AccountMapOut(
        id=mapping.id,
        qbo_account_id=mapping.qbo_account_id,
        qbo_account_name=mapping.qbo_account_name,
        qbo_account_type=mapping.qbo_account_type,
        qbo_account_number=mapping.qbo_account_number,
        gl_account_id=mapping.gl_account_id,
        gl_account_name=account.name if account else None,
        manual_override=mapping.manual_override,
    )


# ─── Sync ──────────────────────────────────────────────────────────────────

@router.post("/sync", response_model=SyncResultOut)
async def sync_now(
    payload: SyncRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    """Push posted journal entries created since the last cursor."""
    org_id = _require_org(current_user)
    conn = await _require_connection(db, org_id)
    try:
        result = await svc.sync_now(db, org_id, conn, limit=(payload.limit if payload else None))
    except QuickBooksApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return SyncResultOut(**{k: v for k, v in result.items() if k in SyncResultOut.model_fields})


@router.get("/logs", response_model=list[SyncLogOut])
async def list_sync_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _feature: User = Depends(AdvancedAccounting),
):
    org_id = _require_org(current_user)
    logs = await svc.recent_logs(db, org_id)
    return [
        SyncLogOut(
            id=log.id,
            direction=log.direction,
            status=log.status,
            cursor_before=log.cursor_before,
            cursor_after=log.cursor_after,
            counts=log.counts,
            error_message=log.error_message,
            started_at=log.started_at,
            finished_at=log.finished_at,
        )
        for log in logs
    ]

"""Live bank-feed API router — ``/api/v1/bank-feed``.

Plaid-backed bank connectivity that replaces the manual CSV/OFX upload described
in ``app.routers.bank``. Fetched transactions land in the same
``bank_transactions`` register, so reconciliation is unchanged.

Flow:
  1. ``POST /link-token`` mints a Plaid Link token for the browser widget.
  2. ``POST /connections`` exchanges the resulting public token and binds the
     Item to one local bank account (access token encrypted at rest).
  3. ``POST /connections/{id}/sync`` walks ``/transactions/sync`` from the stored
     cursor and applies added / modified / removed transactions.
  4. ``DELETE /connections/{id}`` removes the Item; imported rows are kept.

When ``PLAID_CLIENT_ID``/``PLAID_SECRET`` are unset every endpoint reports an
unconfigured provider instead of erroring, matching
``app.utils.payment_processor``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.bank_account import BankAccount
from app.models.external_sync import BankFeedConnection
from app.models.user import User
from app.services.bank_feed import sync_service as svc
from app.services.bank_feed.plaid_client import PlaidApiError, PlaidClient
from app.services import organization_integration_settings as org_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Finance staff only, mirroring the rest of the accounting surface.
FinanceUser = require_role("admin", "accountant")


def _require_org(current_user: User) -> uuid.UUID:
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    return current_user.organization_id


# ─── Schemas ───────────────────────────────────────────────────────────────

class ProviderStatusOut(BaseModel):
    configured: bool
    provider: str = "plaid"
    environment: str | None = None
    detail: str | None = None


class LinkTokenOut(BaseModel):
    configured: bool
    link_token: str | None = None
    expiration: str | None = None
    detail: str | None = None


class ConnectionCreate(BaseModel):
    public_token: str = Field(min_length=1)
    bank_account_id: uuid.UUID
    # Optional Plaid account id when the Item exposes more than one account.
    provider_account_id: str | None = None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    item_id: str
    institution_name: str | None
    provider_account_id: str | None
    account_mask: str | None
    bank_account_id: uuid.UUID
    bank_account_name: str | None = None
    status: str
    is_enabled: bool
    last_sync_at: datetime | None
    last_error: str | None
    has_cursor: bool
    created_at: datetime


class SyncResultOut(BaseModel):
    configured: bool = True
    imported: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    retained: int = 0
    pages: int = 0
    error: str | None = None
    detail: str | None = None


class SyncLogOut(BaseModel):
    id: uuid.UUID
    direction: str
    status: str
    counts: dict | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


def _connection_out(
    conn: BankFeedConnection, bank_account: BankAccount | None = None
) -> ConnectionOut:
    return ConnectionOut(
        id=conn.id,
        provider=conn.provider,
        item_id=conn.item_id,
        institution_name=conn.institution_name,
        provider_account_id=conn.provider_account_id,
        account_mask=conn.account_mask,
        bank_account_id=conn.bank_account_id,
        bank_account_name=bank_account.name if bank_account else None,
        status=conn.status,
        is_enabled=conn.is_enabled,
        last_sync_at=conn.last_sync_at,
        last_error=conn.last_error,
        has_cursor=bool(conn.last_sync_cursor),
        created_at=conn.created_at,
    )


# ─── Provider status / Link ────────────────────────────────────────────────

@router.get("/status", response_model=ProviderStatusOut)
async def provider_status(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(FinanceUser)
):
    config = await org_settings.resolve(db, _require_org(current_user), "plaid")
    if not config.is_enabled or not config.client_id or not config.secret:
        return ProviderStatusOut(
            configured=False, detail="Bank feed provider is not configured."
        )
    return ProviderStatusOut(configured=True, environment=config.environment)


@router.post("/link-token", response_model=LinkTokenOut)
async def create_link_token(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(FinanceUser)
):
    """Mint a short-lived Plaid Link token for the browser widget."""
    org_id = _require_org(current_user)
    config = await org_settings.resolve(db, org_id, "plaid")
    if not config.is_enabled or not config.client_id or not config.secret:
        return LinkTokenOut(
            configured=False, detail="Bank feed provider is not configured."
        )
    try:
        result = await PlaidClient(config=config).create_link_token(
            client_user_id=str(org_id), client_name="Portfolio Desk"
        )
    except PlaidApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return LinkTokenOut(
        configured=True,
        link_token=result.get("link_token"),
        expiration=result.get("expiration"),
    )


# ─── Connections ───────────────────────────────────────────────────────────

@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = _require_org(current_user)
    connections = await svc.list_connections(db, org_id)
    out: list[ConnectionOut] = []
    for conn in connections:
        out.append(_connection_out(conn, await db.get(BankAccount, conn.bank_account_id)))
    return out


@router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Exchange the Link public token and bind the Item to a bank account."""
    org_id = _require_org(current_user)
    config = await org_settings.resolve(db, org_id, "plaid")
    if not config.is_enabled or not config.client_id or not config.secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bank feed provider is not configured.",
        )

    bank_account = await db.get(BankAccount, payload.bank_account_id)
    if bank_account is None or bank_account.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        )

    client = PlaidClient(config=config)
    try:
        exchange = await client.exchange_public_token(payload.public_token)
        access_token = exchange.get("access_token")
        item_id = exchange.get("item_id")
        if not access_token or not item_id:
            raise PlaidApiError("Plaid did not return an access token for this Item.")
        institution_name, mask = await _describe_item(
            client, access_token, payload.provider_account_id
        )
    except PlaidApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    conn = await svc.store_connection(
        db,
        org_id,
        bank_account_id=payload.bank_account_id,
        access_token=access_token,
        item_id=item_id,
        institution_name=institution_name,
        provider_account_id=payload.provider_account_id,
        account_mask=mask,
    )
    return _connection_out(conn, bank_account)


async def _describe_item(
    client: PlaidClient, access_token: str, provider_account_id: str | None
) -> tuple[str | None, str | None]:
    """Best-effort institution name and account mask for display."""
    institution_name: str | None = None
    mask: str | None = None
    try:
        accounts = await client.get_accounts(access_token)
    except PlaidApiError:
        return None, None
    for account in accounts.get("accounts") or []:
        if provider_account_id and account.get("account_id") != provider_account_id:
            continue
        mask = account.get("mask")
        break
    institution_id = (accounts.get("item") or {}).get("institution_id")
    if institution_id:
        try:
            info = await client.get_institution(institution_id)
            institution_name = (info.get("institution") or {}).get("name")
        except PlaidApiError:
            institution_name = None
    return institution_name, mask


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = _require_org(current_user)
    conn = await svc.get_connection(db, org_id, connection_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank feed connection not found"
        )
    await svc.disconnect(db, conn)


@router.post("/connections/{connection_id}/sync", response_model=SyncResultOut)
async def sync_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Pull new, changed and removed transactions since the stored cursor."""
    org_id = _require_org(current_user)
    conn = await svc.get_connection(db, org_id, connection_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank feed connection not found"
        )
    try:
        result = await svc.sync_transactions(db, conn)
    except PlaidApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return SyncResultOut(**{k: v for k, v in result.items() if k in SyncResultOut.model_fields})


@router.get("/logs", response_model=list[SyncLogOut])
async def list_sync_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = _require_org(current_user)
    logs = await svc.recent_logs(db, org_id)
    return [
        SyncLogOut(
            id=log.id,
            direction=log.direction,
            status=log.status,
            counts=log.counts,
            error_message=log.error_message,
            started_at=log.started_at,
            finished_at=log.finished_at,
        )
        for log in logs
    ]

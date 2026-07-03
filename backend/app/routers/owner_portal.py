"""Owner portal — token-gated endpoints for external property-owner access (Phase 2.6).

Extends the existing portal-token pattern (client, vendor, resident portals) to
property owners. A staff member mints a single-use invite; the owner redeems it
for a persistent ``X-Owner-Token`` credential used to:

  * view their owner profile and assigned properties,
  * read their trust ledger and a running balance,
  * pull an owner statement (opening/closing balances + activity) for a period,
  * review their distributions/payouts.

The portal is read-only; tax identifiers are never exposed. Portal accounts
reuse :class:`ClientPortalAccount` with ``entity_type="owner"``.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.client_portal_account import ClientPortalAccount
from app.models.owner import (
    OwnerDistribution,
    OwnerLedgerEntry,
    OwnerProperty,
    PropertyOwner,
)
from app.models.user import User
from app.services import owner_service as svc

router = APIRouter()

_OWNER_ENTITY_TYPE = "owner"
_TOKEN_TTL_DAYS = 90
_SIGNUP_TTL_DAYS = 14


# ─── Schemas ──────────────────────────────────────────────────────────────────

class InviteResponse(BaseModel):
    signup_token: str
    signup_url: str
    expires_at: datetime


class SignupRequest(BaseModel):
    token: str


class PortalSession(BaseModel):
    portal_token: str
    portal_url: str
    expires_at: datetime


class OwnerProfile(BaseModel):
    id: uuid.UUID
    owner_type: str
    name: str
    email: str | None
    phone: str | None
    status: str
    currency: str

    model_config = {"from_attributes": True}


class PortalProperty(BaseModel):
    office_id: uuid.UUID
    ownership_percent: Decimal
    start_date: date | None
    end_date: date | None

    model_config = {"from_attributes": True}


class PortalLedgerEntry(BaseModel):
    id: uuid.UUID
    entry_date: date
    entry_type: str
    amount: Decimal
    description: str | None
    currency: str

    model_config = {"from_attributes": True}


class PortalBalance(BaseModel):
    currency: str
    balance: Decimal


class PortalDistribution(BaseModel):
    id: uuid.UUID
    distribution_date: date
    amount: Decimal
    method: str
    reference: str | None
    status: str
    currency: str

    model_config = {"from_attributes": True}


class PortalStatement(BaseModel):
    currency: str
    start_date: date | None
    end_date: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    totals: dict[str, Decimal]
    lines: list[PortalLedgerEntry]


# ─── Token helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_owner_account(
    x_owner_token: str = Header(None, alias="X-Owner-Token"),
    db: AsyncSession = Depends(get_db),
) -> ClientPortalAccount:
    if not x_owner_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing owner portal token")
    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.portal_token == x_owner_token,
                ClientPortalAccount.entity_type == _OWNER_ENTITY_TYPE,
            )
        )
    ).scalar_one_or_none()
    if account is None or account.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid owner portal token")
    expires = _aware(account.portal_token_expires_at)
    if expires is not None and expires < _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Owner portal token expired")
    account.last_active_at = _now()
    return account


async def _owner_for(db: AsyncSession, account: ClientPortalAccount) -> PropertyOwner:
    owner = (
        await db.execute(
            select(PropertyOwner).where(
                PropertyOwner.id == account.entity_id,
                PropertyOwner.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Owner not found")
    return owner


# ─── Staff: invite ────────────────────────────────────────────────────────────

@router.post("/owner-portal/invite", response_model=InviteResponse)
async def invite_owner(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor", "accountant")),
):
    """Mint (or refresh) a single-use portal invite for an owner."""
    owner_id = payload.get("owner_id")
    if not owner_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="owner_id is required")
    owner = (
        await db.execute(
            select(PropertyOwner).where(
                PropertyOwner.id == uuid.UUID(str(owner_id)),
                PropertyOwner.organization_id == current_user.organization_id,
                PropertyOwner.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Owner not found")

    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.entity_type == _OWNER_ENTITY_TYPE,
                ClientPortalAccount.entity_id == owner.id,
                ClientPortalAccount.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()

    signup_token = secrets.token_hex(32)
    expires = _now() + timedelta(days=_SIGNUP_TTL_DAYS)
    if account is None:
        account = ClientPortalAccount(
            organization_id=current_user.organization_id,
            entity_type=_OWNER_ENTITY_TYPE,
            entity_id=owner.id,
        )
        db.add(account)
    account.signup_token = signup_token
    account.signup_token_expires_at = expires
    account.revoked_at = None
    await db.commit()
    return InviteResponse(
        signup_token=signup_token,
        signup_url=f"/owner-portal/signup?token={signup_token}",
        expires_at=expires,
    )


# ─── Public: signup ───────────────────────────────────────────────────────────

@router.post("/owner-portal/signup", response_model=PortalSession)
async def owner_signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
):
    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.signup_token == payload.token,
                ClientPortalAccount.entity_type == _OWNER_ENTITY_TYPE,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid signup token")
    expires = _aware(account.signup_token_expires_at)
    if expires is not None and expires < _now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signup token expired")

    portal_token = secrets.token_hex(32)
    portal_expires = _now() + timedelta(days=_TOKEN_TTL_DAYS)
    account.portal_token = portal_token
    account.portal_token_expires_at = portal_expires
    account.signup_token = None
    account.signup_token_expires_at = None
    account.activated_at = _now()
    await db.commit()
    return PortalSession(
        portal_token=portal_token,
        portal_url=f"/owner-portal?token={portal_token}",
        expires_at=portal_expires,
    )


# ─── Owner: profile / properties / ledger / statement / distributions ─────────

@router.get("/owner-portal/me", response_model=OwnerProfile)
async def portal_me(
    account: ClientPortalAccount = Depends(get_owner_account),
    db: AsyncSession = Depends(get_db),
):
    owner = await _owner_for(db, account)
    await db.commit()
    return OwnerProfile.model_validate(owner)


@router.get("/owner-portal/properties", response_model=list[PortalProperty])
async def portal_properties(
    account: ClientPortalAccount = Depends(get_owner_account),
    db: AsyncSession = Depends(get_db),
):
    owner = await _owner_for(db, account)
    links = (
        await db.execute(
            select(OwnerProperty)
            .where(OwnerProperty.owner_id == owner.id)
            .order_by(OwnerProperty.created_at)
        )
    ).scalars().all()
    await db.commit()
    return [PortalProperty.model_validate(l) for l in links]


@router.get("/owner-portal/ledger", response_model=list[PortalLedgerEntry])
async def portal_ledger(
    account: ClientPortalAccount = Depends(get_owner_account),
    db: AsyncSession = Depends(get_db),
):
    owner = await _owner_for(db, account)
    entries = (
        await db.execute(
            select(OwnerLedgerEntry)
            .where(OwnerLedgerEntry.owner_id == owner.id)
            .order_by(OwnerLedgerEntry.entry_date, OwnerLedgerEntry.created_at)
        )
    ).scalars().all()
    await db.commit()
    return [PortalLedgerEntry.model_validate(e) for e in entries]


@router.get("/owner-portal/balance", response_model=PortalBalance)
async def portal_balance(
    account: ClientPortalAccount = Depends(get_owner_account),
    db: AsyncSession = Depends(get_db),
):
    owner = await _owner_for(db, account)
    balance = await svc.owner_balance(db, owner.organization_id, owner.id)
    await db.commit()
    return PortalBalance(currency=owner.currency, balance=balance)


@router.get("/owner-portal/statement", response_model=PortalStatement)
async def portal_statement(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    account: ClientPortalAccount = Depends(get_owner_account),
    db: AsyncSession = Depends(get_db),
):
    owner = await _owner_for(db, account)
    data = await svc.generate_statement(
        db, owner.organization_id, owner, start_date=start_date, end_date=end_date
    )
    await db.commit()
    return PortalStatement(
        currency=data["currency"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        opening_balance=data["opening_balance"],
        closing_balance=data["closing_balance"],
        totals=data["totals"],
        lines=[PortalLedgerEntry.model_validate(e) for e in data["lines"]],
    )


@router.get("/owner-portal/distributions", response_model=list[PortalDistribution])
async def portal_distributions(
    account: ClientPortalAccount = Depends(get_owner_account),
    db: AsyncSession = Depends(get_db),
):
    owner = await _owner_for(db, account)
    dists = (
        await db.execute(
            select(OwnerDistribution)
            .where(OwnerDistribution.owner_id == owner.id)
            .order_by(OwnerDistribution.distribution_date.desc(), OwnerDistribution.created_at.desc())
        )
    ).scalars().all()
    await db.commit()
    return [PortalDistribution.model_validate(d) for d in dists]

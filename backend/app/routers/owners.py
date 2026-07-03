"""Owner / trust accounting API router (Phase 2.6) — ``/api/v1/owners``.

Property owners (the people/entities whose buildings the org manages), their
property assignments, the per-owner trust ledger, distributions/payouts, owner
statements, and segregated trust/escrow accounts with a compliance-review
workflow.

Every ledger movement posts through the shared general ledger (owner funds are a
``Due to Owners`` liability), so trust balances reconcile with the GL. Endpoints
are gated to the ``admin`` and ``accountant`` roles, matching the AR/AP/rent
routers, except trust-account compliance review which requires ``admin``.
Amounts are USD-only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.owner import (
    COMPLIANCE_STATUSES,
    DISTRIBUTION_METHODS,
    DISTRIBUTION_STATUSES,
    LEDGER_ENTRY_TYPES,
    OWNER_STATUSES,
    OWNER_TYPES,
    TRUST_ACCOUNT_STATUSES,
    OwnerDistribution,
    OwnerLedgerEntry,
    OwnerProperty,
    PropertyOwner,
    TrustAccount,
)
from app.models.user import User
from app.services import owner_service as svc
from app.services.owner_service import OwnerError

router = APIRouter()
# Trust/escrow accounts get their own router so their static ``/trust-accounts``
# path can be mounted ahead of the ``/{owner_id}`` owner routes (avoiding the
# path-parameter collision).
trust_router = APIRouter()

# Finance staff only, matching the AR/AP/rent routers.
FinanceUser = require_role("admin", "accountant")
# Compliance sign-off on trust accounts is admin-only.
Admin = require_role("admin")


# ─── Schemas: Owner ───────────────────────────────────────────────────────────

class OwnerCreate(BaseModel):
    owner_type: str = "individual"
    name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    tax_id: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    management_fee_percent: Decimal = Decimal("0")
    status: str = "active"
    currency: str = "USD"
    notes: str | None = None


class OwnerUpdate(BaseModel):
    owner_type: str | None = None
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    tax_id: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    management_fee_percent: Decimal | None = None
    status: str | None = None
    notes: str | None = None


class OwnerResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    owner_type: str
    name: str
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None
    tax_id: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    management_fee_percent: Decimal
    status: str
    currency: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OwnerPropertyCreate(BaseModel):
    office_id: uuid.UUID
    ownership_percent: Decimal = Decimal("100")
    management_fee_percent: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None


class OwnerPropertyResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    office_id: uuid.UUID
    ownership_percent: Decimal
    management_fee_percent: Decimal | None
    start_date: date | None
    end_date: date | None

    model_config = {"from_attributes": True}


class LedgerEntryCreate(BaseModel):
    entry_type: str
    amount: Decimal
    entry_date: date | None = None
    office_id: uuid.UUID | None = None
    description: str | None = None
    post_gl: bool = True


class LedgerEntryResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    office_id: uuid.UUID | None
    entry_date: date
    entry_type: str
    amount: Decimal
    description: str | None
    currency: str
    source: str | None
    source_ref: str | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BalanceResponse(BaseModel):
    owner_id: uuid.UUID
    currency: str
    balance: Decimal


class DistributionCreate(BaseModel):
    amount: Decimal
    distribution_date: date | None = None
    method: str = "ach"
    reference: str | None = None
    memo: str | None = None
    trust_account_id: uuid.UUID | None = None


class DistributionResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    distribution_date: date
    amount: Decimal
    method: str
    reference: str | None
    status: str
    memo: str | None
    currency: str
    trust_account_id: uuid.UUID | None
    ledger_entry_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StatementResponse(BaseModel):
    owner_id: uuid.UUID
    owner_name: str
    currency: str
    start_date: date | None
    end_date: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    totals: dict[str, Decimal]
    lines: list[LedgerEntryResponse]


class TrustAccountCreate(BaseModel):
    name: str
    bank_name: str | None = None
    account_number_last4: str | None = None
    gl_account_id: uuid.UUID | None = None
    currency: str = "USD"
    status: str = "active"
    notes: str | None = None


class TrustAccountUpdate(BaseModel):
    name: str | None = None
    bank_name: str | None = None
    account_number_last4: str | None = None
    gl_account_id: uuid.UUID | None = None
    status: str | None = None
    notes: str | None = None


class TrustAccountResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    bank_name: str | None
    account_number_last4: str | None
    gl_account_id: uuid.UUID | None
    currency: str
    status: str
    notes: str | None
    compliance_review_required: bool
    compliance_status: str
    compliance_reviewed_at: datetime | None
    compliance_reviewed_by_id: uuid.UUID | None
    compliance_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ComplianceReviewRequest(BaseModel):
    compliance_status: str
    notes: str | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _validate_enum(value: str | None, allowed: tuple[str, ...], field: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field} '{value}'. Must be one of: {', '.join(allowed)}.",
        )


async def _get_owner(db: AsyncSession, owner_id: uuid.UUID, org_id) -> PropertyOwner:
    try:
        return await svc.load_owner(db, org_id, owner_id)
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def _get_trust_account(db: AsyncSession, account_id: uuid.UUID, org_id) -> TrustAccount:
    try:
        return await svc.load_trust_account(db, org_id, account_id)
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ─── Owners CRUD ──────────────────────────────────────────────────────────────

@router.get("/", response_model=list[OwnerResponse])
async def list_owners(
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = select(PropertyOwner).where(
        PropertyOwner.organization_id == current_user.organization_id,
        PropertyOwner.is_deleted.is_(False),
    )
    if status_filter:
        stmt = stmt.where(PropertyOwner.status == status_filter)
    stmt = stmt.order_by(PropertyOwner.name)
    owners = (await db.execute(stmt)).scalars().all()
    return [OwnerResponse.model_validate(o) for o in owners]


@router.post("/", response_model=OwnerResponse, status_code=status.HTTP_201_CREATED)
async def create_owner(
    payload: OwnerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    _validate_enum(payload.owner_type, OWNER_TYPES, "owner_type")
    _validate_enum(payload.status, OWNER_STATUSES, "status")
    owner = PropertyOwner(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    return OwnerResponse.model_validate(owner)


@router.get("/{owner_id}", response_model=OwnerResponse)
async def get_owner(
    owner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    return OwnerResponse.model_validate(owner)


@router.patch("/{owner_id}", response_model=OwnerResponse)
async def update_owner(
    owner_id: uuid.UUID,
    payload: OwnerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_enum(data.get("owner_type"), OWNER_TYPES, "owner_type")
    _validate_enum(data.get("status"), OWNER_STATUSES, "status")
    for key, value in data.items():
        setattr(owner, key, value)
    await db.commit()
    await db.refresh(owner)
    return OwnerResponse.model_validate(owner)


@router.delete("/{owner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_owner(
    owner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    owner.is_deleted = True
    await db.commit()


# ─── Property assignments ─────────────────────────────────────────────────────

@router.get("/{owner_id}/properties", response_model=list[OwnerPropertyResponse])
async def list_owner_properties(
    owner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _get_owner(db, owner_id, current_user.organization_id)
    links = (
        await db.execute(
            select(OwnerProperty)
            .where(OwnerProperty.owner_id == owner_id)
            .order_by(OwnerProperty.created_at)
        )
    ).scalars().all()
    return [OwnerPropertyResponse.model_validate(l) for l in links]


@router.post(
    "/{owner_id}/properties",
    response_model=OwnerPropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_owner_property(
    owner_id: uuid.UUID,
    payload: OwnerPropertyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    try:
        link = await svc.assign_property(
            db,
            current_user.organization_id,
            owner,
            office_id=payload.office_id,
            ownership_percent=payload.ownership_percent,
            management_fee_percent=payload.management_fee_percent,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return OwnerPropertyResponse.model_validate(link)


@router.delete(
    "/{owner_id}/properties/{link_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unassign_owner_property(
    owner_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _get_owner(db, owner_id, current_user.organization_id)
    link = (
        await db.execute(
            select(OwnerProperty).where(
                OwnerProperty.id == link_id,
                OwnerProperty.owner_id == owner_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property link not found.")
    await db.delete(link)
    await db.commit()


# ─── Ledger ───────────────────────────────────────────────────────────────────

@router.get("/{owner_id}/ledger", response_model=list[LedgerEntryResponse])
async def list_ledger(
    owner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _get_owner(db, owner_id, current_user.organization_id)
    entries = (
        await db.execute(
            select(OwnerLedgerEntry)
            .where(
                OwnerLedgerEntry.owner_id == owner_id,
                OwnerLedgerEntry.organization_id == current_user.organization_id,
            )
            .order_by(OwnerLedgerEntry.entry_date, OwnerLedgerEntry.created_at)
        )
    ).scalars().all()
    return [LedgerEntryResponse.model_validate(e) for e in entries]


@router.post(
    "/{owner_id}/ledger",
    response_model=LedgerEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ledger_entry(
    owner_id: uuid.UUID,
    payload: LedgerEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    _validate_enum(payload.entry_type, LEDGER_ENTRY_TYPES, "entry_type")
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    try:
        entry = await svc.record_ledger_entry(
            db,
            current_user.organization_id,
            owner,
            entry_type=payload.entry_type,
            amount=payload.amount,
            entry_date=payload.entry_date,
            office_id=payload.office_id,
            description=payload.description,
            post_gl=payload.post_gl,
            posted_by_id=current_user.id,
        )
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return LedgerEntryResponse.model_validate(entry)


@router.get("/{owner_id}/balance", response_model=BalanceResponse)
async def get_balance(
    owner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    balance = await svc.owner_balance(db, current_user.organization_id, owner_id)
    return BalanceResponse(owner_id=owner_id, currency=owner.currency, balance=balance)


# ─── Statements ───────────────────────────────────────────────────────────────

@router.get("/{owner_id}/statement", response_model=StatementResponse)
async def get_statement(
    owner_id: uuid.UUID,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    data = await svc.generate_statement(
        db,
        current_user.organization_id,
        owner,
        start_date=start_date,
        end_date=end_date,
    )
    return StatementResponse(
        owner_id=data["owner_id"],
        owner_name=data["owner_name"],
        currency=data["currency"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        opening_balance=data["opening_balance"],
        closing_balance=data["closing_balance"],
        totals=data["totals"],
        lines=[LedgerEntryResponse.model_validate(e) for e in data["lines"]],
    )


# ─── Distributions / payouts ──────────────────────────────────────────────────

@router.get("/{owner_id}/distributions", response_model=list[DistributionResponse])
async def list_distributions(
    owner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _get_owner(db, owner_id, current_user.organization_id)
    dists = (
        await db.execute(
            select(OwnerDistribution)
            .where(
                OwnerDistribution.owner_id == owner_id,
                OwnerDistribution.organization_id == current_user.organization_id,
            )
            .order_by(OwnerDistribution.distribution_date.desc(), OwnerDistribution.created_at.desc())
        )
    ).scalars().all()
    return [DistributionResponse.model_validate(d) for d in dists]


@router.post(
    "/{owner_id}/distributions",
    response_model=DistributionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution(
    owner_id: uuid.UUID,
    payload: DistributionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    _validate_enum(payload.method, DISTRIBUTION_METHODS, "method")
    owner = await _get_owner(db, owner_id, current_user.organization_id)
    try:
        dist = await svc.create_distribution(
            db,
            current_user.organization_id,
            owner,
            amount=payload.amount,
            distribution_date=payload.distribution_date,
            method=payload.method,
            reference=payload.reference,
            memo=payload.memo,
            trust_account_id=payload.trust_account_id,
        )
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return DistributionResponse.model_validate(dist)


async def _get_distribution(
    db: AsyncSession, owner_id: uuid.UUID, distribution_id: uuid.UUID, org_id
) -> OwnerDistribution:
    dist = (
        await db.execute(
            select(OwnerDistribution).where(
                OwnerDistribution.id == distribution_id,
                OwnerDistribution.owner_id == owner_id,
                OwnerDistribution.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found.")
    return dist


@router.post(
    "/{owner_id}/distributions/{distribution_id}/pay",
    response_model=DistributionResponse,
)
async def pay_distribution(
    owner_id: uuid.UUID,
    distribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _get_owner(db, owner_id, current_user.organization_id)
    dist = await _get_distribution(db, owner_id, distribution_id, current_user.organization_id)
    try:
        dist = await svc.mark_distribution_paid(
            db, current_user.organization_id, dist, posted_by_id=current_user.id
        )
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return DistributionResponse.model_validate(dist)


@router.post(
    "/{owner_id}/distributions/{distribution_id}/void",
    response_model=DistributionResponse,
)
async def void_distribution_endpoint(
    owner_id: uuid.UUID,
    distribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _get_owner(db, owner_id, current_user.organization_id)
    dist = await _get_distribution(db, owner_id, distribution_id, current_user.organization_id)
    try:
        dist = await svc.void_distribution(db, current_user.organization_id, dist)
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return DistributionResponse.model_validate(dist)


# ─── Trust / escrow accounts ──────────────────────────────────────────────────

@trust_router.get("", response_model=list[TrustAccountResponse])
async def list_trust_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    accounts = (
        await db.execute(
            select(TrustAccount)
            .where(
                TrustAccount.organization_id == current_user.organization_id,
                TrustAccount.is_deleted.is_(False),
            )
            .order_by(TrustAccount.name)
        )
    ).scalars().all()
    return [TrustAccountResponse.model_validate(a) for a in accounts]


@trust_router.post(
    "",
    response_model=TrustAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_trust_account(
    payload: TrustAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    _validate_enum(payload.status, TRUST_ACCOUNT_STATUSES, "status")
    account = TrustAccount(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return TrustAccountResponse.model_validate(account)


@trust_router.get("/{account_id}", response_model=TrustAccountResponse)
async def get_trust_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    account = await _get_trust_account(db, account_id, current_user.organization_id)
    return TrustAccountResponse.model_validate(account)


@trust_router.patch("/{account_id}", response_model=TrustAccountResponse)
async def update_trust_account(
    account_id: uuid.UUID,
    payload: TrustAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    account = await _get_trust_account(db, account_id, current_user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_enum(data.get("status"), TRUST_ACCOUNT_STATUSES, "status")
    for key, value in data.items():
        setattr(account, key, value)
    await db.commit()
    await db.refresh(account)
    return TrustAccountResponse.model_validate(account)


@trust_router.post(
    "/{account_id}/review", response_model=TrustAccountResponse
)
async def review_trust_account(
    account_id: uuid.UUID,
    payload: ComplianceReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    """Record a compliance-review decision on a trust/escrow account (admin only)."""
    _validate_enum(payload.compliance_status, COMPLIANCE_STATUSES, "compliance_status")
    account = await _get_trust_account(db, account_id, current_user.organization_id)
    try:
        account = await svc.review_trust_account(
            db,
            current_user.organization_id,
            account,
            compliance_status=payload.compliance_status,
            notes=payload.notes,
            reviewed_by_id=current_user.id,
        )
    except OwnerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return TrustAccountResponse.model_validate(account)


@trust_router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trust_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    account = await _get_trust_account(db, account_id, current_user.organization_id)
    account.is_deleted = True
    await db.commit()

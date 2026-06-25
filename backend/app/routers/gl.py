"""General-ledger API router (Phase 2) — `/api/v1/gl`.

All write endpoints (and reads) are gated to the `admin` and `accountant`
roles so finance data is only visible to finance staff.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.general_ledger import (
    AccountingPeriod,
    GLAccount,
    JournalEntry,
    JournalEntryLine,
)
from app.models.lease import Lease
from app.models.user import User
from app.services import gl_service
from app.services.gl_service import GLError

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    code: str
    name: str
    type: str


class AccountUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    is_active: bool | None = None


class AccountResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    type: str
    normal_balance: str
    is_active: bool

    model_config = {"from_attributes": True}


class PeriodResponse(BaseModel):
    id: uuid.UUID
    year: int
    month: int
    status: str
    closed_at: datetime | None
    closed_by_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class JournalLineInput(BaseModel):
    account_id: uuid.UUID
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str | None = None


class JournalEntryCreate(BaseModel):
    entry_date: date
    memo: str | None = None
    lines: list[JournalLineInput] = Field(min_length=1)


class JournalLineResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_code: str
    account_name: str
    line_number: int
    debit: Decimal
    credit: Decimal
    memo: str | None

    model_config = {"from_attributes": True}


class JournalEntryResponse(BaseModel):
    id: uuid.UUID
    entry_date: date
    memo: str | None
    source: str
    source_ref: str | None
    status: str
    posted_at: datetime | None
    lines: list[JournalLineResponse]

    model_config = {"from_attributes": True}


class TrialBalanceRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    balance_side: str


def _entry_to_response(entry: JournalEntry) -> JournalEntryResponse:
    return JournalEntryResponse(
        id=entry.id,
        entry_date=entry.entry_date,
        memo=entry.memo,
        source=entry.source,
        source_ref=entry.source_ref,
        status=entry.status,
        posted_at=entry.posted_at,
        lines=[
            JournalLineResponse(
                id=line.id,
                account_id=line.account_id,
                account_code=line.account.code,
                account_name=line.account.name,
                line_number=line.line_number,
                debit=line.debit,
                credit=line.credit,
                memo=line.memo,
            )
            for line in entry.lines
        ],
    )


# ─── Chart of accounts ──────────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """List the chart of accounts, seeding defaults on first use."""
    await gl_service.seed_default_accounts(db, current_user.organization_id)
    result = await db.execute(
        select(GLAccount)
        .where(GLAccount.organization_id == current_user.organization_id)
        .order_by(GLAccount.code)
    )
    return [AccountResponse.model_validate(a) for a in result.scalars().all()]


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    try:
        gl_service.validate_account_type(payload.type)
    except GLError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    existing = (
        await db.execute(
            select(GLAccount).where(
                GLAccount.organization_id == current_user.organization_id,
                GLAccount.code == payload.code,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Account code '{payload.code}' already exists.",
        )

    account = GLAccount(
        organization_id=current_user.organization_id,
        code=payload.code,
        name=payload.name,
        type=payload.type,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return AccountResponse.model_validate(account)


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    account = (
        await db.execute(
            select(GLAccount).where(
                GLAccount.id == account_id,
                GLAccount.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    if payload.type is not None:
        try:
            gl_service.validate_account_type(payload.type)
        except GLError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    await db.commit()
    await db.refresh(account)
    return AccountResponse.model_validate(account)


# ─── Periods ─────────────────────────────────────────────────────────────────

@router.get("/periods", response_model=list[PeriodResponse])
async def list_periods(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    result = await db.execute(
        select(AccountingPeriod)
        .where(AccountingPeriod.organization_id == current_user.organization_id)
        .order_by(AccountingPeriod.year.desc(), AccountingPeriod.month.desc())
    )
    return [PeriodResponse.model_validate(p) for p in result.scalars().all()]


@router.post("/periods/{year}/{month}/close", response_model=PeriodResponse)
async def close_period(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    try:
        period = await gl_service.close_period(
            db, current_user.organization_id, year, month, current_user.id
        )
    except GLError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return PeriodResponse.model_validate(period)


@router.post("/periods/{year}/{month}/reopen", response_model=PeriodResponse)
async def reopen_period(
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    try:
        period = await gl_service.reopen_period(
            db, current_user.organization_id, year, month
        )
    except GLError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return PeriodResponse.model_validate(period)


# ─── Journal entries ──────────────────────────────────────────────────────────

@router.get("/journal-entries", response_model=list[JournalEntryResponse])
async def list_journal_entries(
    source: str | None = Query(default=None),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(JournalEntry)
        .where(JournalEntry.organization_id == current_user.organization_id)
        .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())
    )
    if source:
        stmt = stmt.where(JournalEntry.source == source)
    if year is not None and month is not None:
        stmt = stmt.where(
            JournalEntry.entry_date >= date(year, month, 1),
            JournalEntry.entry_date <= date(year, month, calendar.monthrange(year, month)[1]),
        )
    result = await db.execute(stmt)
    return [_entry_to_response(e) for e in result.scalars().unique().all()]


@router.post("/journal-entries", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_journal_entry(
    payload: JournalEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await gl_service.seed_default_accounts(db, current_user.organization_id)
    lines = [
        {
            "account_id": line.account_id,
            "debit": line.debit,
            "credit": line.credit,
            "memo": line.memo,
        }
        for line in payload.lines
    ]
    try:
        entry = await gl_service.create_journal_entry(
            db,
            current_user.organization_id,
            entry_date=payload.entry_date,
            lines=lines,
            memo=payload.memo,
            source="manual",
            posted_by_id=current_user.id,
        )
    except GLError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    # Re-load with account relationships for the response.
    entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id == entry.id)
            .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
        )
    ).scalar_one()
    return _entry_to_response(entry)


@router.post("/journal-entries/post-lease/{lease_id}", response_model=list[JournalEntryResponse])
async def post_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Post (or re-post) a lease's ASC 842 / IFRS 16 schedule into the GL."""
    lease = (
        await db.execute(
            select(Lease).where(
                Lease.id == lease_id,
                Lease.organization_id == current_user.organization_id,
                Lease.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    try:
        entries = await gl_service.post_lease_entries(
            db, current_user.organization_id, lease, posted_by_id=current_user.id
        )
    except GLError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    ids = [e.id for e in entries]
    if not ids:
        return []
    loaded = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id.in_(ids))
            .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
            .order_by(JournalEntry.entry_date)
        )
    ).scalars().unique().all()
    return [_entry_to_response(e) for e in loaded]


# ─── Trial balance & export ────────────────────────────────────────────────────

@router.get("/trial-balance", response_model=list[TrialBalanceRow])
async def get_trial_balance(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    rows = await gl_service.trial_balance(
        db, current_user.organization_id, year=year, month=month
    )
    return [TrialBalanceRow(**r) for r in rows]


@router.get("/export")
async def export_journal(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Export posted journal entries as a QuickBooks-compatible CSV."""
    csv_text = await gl_service.export_journal_csv(
        db, current_user.organization_id, year=year, month=month
    )
    suffix = ""
    if year is not None and month is not None:
        suffix = f"_{year}-{month:02d}"
    elif year is not None:
        suffix = f"_{year}"
    filename = f"general_journal{suffix}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

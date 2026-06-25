"""Accounts-payable-lite API router (Phase 5) — `/api/v1/ap`.

Vendor bills and the payments made against them, posting into the audit-grade
general ledger. All endpoints are gated to the ``admin`` and ``accountant``
roles so finance data stays with finance staff.

Workflow:
  1. ``POST /bills`` captures a draft bill with one or more expense-allocation
     lines (fully editable).
  2. ``PATCH`` / ``DELETE`` edit or remove a draft.
  3. ``POST /bills/{id}/finalize`` locks the bill and posts
     ``Dr expense / Cr Accounts Payable`` to the GL.
  4. ``POST /bills/{id}/payments`` records a cash payment, posting
     ``Dr Accounts Payable / Cr Cash``; the bill's open/partial/paid status is
     derived from its payments.
  5. ``POST /bills/{id}/void`` reverses an unpaid finalized bill's GL entry.

Amounts are USD-only; FX is deferred.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.general_ledger import GLAccount
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_bill import (
    VendorBill,
    VendorBillLine,
    VendorPayment,
)
from app.services import ap_service as svc
from app.services.ap_service import APError

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ────────────────────────────────────────────────────────────────

class BillLineInput(BaseModel):
    account_id: uuid.UUID
    amount: Decimal
    description: str | None = None


class BillCreate(BaseModel):
    vendor_id: uuid.UUID
    bill_date: date
    due_date: date | None = None
    bill_number: str | None = None
    currency: str = "USD"
    memo: str | None = None
    lines: list[BillLineInput]


class BillUpdate(BaseModel):
    bill_date: date | None = None
    due_date: date | None = None
    bill_number: str | None = None
    currency: str | None = None
    memo: str | None = None
    lines: list[BillLineInput] | None = None


class BillLineResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    line_number: int
    description: str | None
    amount: Decimal

    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    payment_date: date
    amount: Decimal
    method: str | None = None
    reference: str | None = None
    memo: str | None = None


class PaymentResponse(BaseModel):
    id: uuid.UUID
    bill_id: uuid.UUID
    payment_date: date
    amount: Decimal
    method: str | None
    reference: str | None
    memo: str | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BillResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    vendor_id: uuid.UUID
    bill_number: str | None
    bill_date: date
    due_date: date | None
    currency: str
    memo: str | None
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    payment_state: str
    status: str
    finalized_at: datetime | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    lines: list[BillLineResponse]
    payments: list[PaymentResponse]


# ─── Helpers ────────────────────────────────────────────────────────────────

def _serialize_bill(bill: VendorBill) -> BillResponse:
    return BillResponse(
        id=bill.id,
        organization_id=bill.organization_id,
        vendor_id=bill.vendor_id,
        bill_number=bill.bill_number,
        bill_date=bill.bill_date,
        due_date=bill.due_date,
        currency=bill.currency,
        memo=bill.memo,
        total_amount=svc.bill_total(bill),
        amount_paid=svc.amount_paid(bill),
        balance_due=svc.balance_due(bill),
        payment_state=svc.payment_state(bill),
        status=bill.status,
        finalized_at=bill.finalized_at,
        journal_entry_id=bill.journal_entry_id,
        created_at=bill.created_at,
        updated_at=bill.updated_at,
        lines=[BillLineResponse.model_validate(line) for line in bill.lines],
        payments=[PaymentResponse.model_validate(p) for p in bill.payments],
    )


async def _get_vendor(db: AsyncSession, vendor_id: uuid.UUID, org_id) -> Vendor:
    vendor = (
        await db.execute(
            select(Vendor).where(
                Vendor.id == vendor_id,
                Vendor.organization_id == org_id,
                Vendor.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return vendor


async def _validate_accounts(db: AsyncSession, account_ids: set[uuid.UUID], org_id) -> None:
    if not account_ids:
        return
    found = (
        await db.execute(
            select(GLAccount.id).where(
                GLAccount.id.in_(account_ids),
                GLAccount.organization_id == org_id,
            )
        )
    ).scalars().all()
    missing = account_ids - set(found)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown account id(s): {', '.join(str(m) for m in missing)}.",
        )


async def _load_bill(db: AsyncSession, bill_id: uuid.UUID, org_id) -> VendorBill:
    # Detach cached instances so the reload builds fresh objects with all
    # columns/relationships populated (derived totals reflect the latest writes).
    db.expunge_all()
    bill = await svc.get_bill(db, bill_id, org_id)
    if not bill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bill not found")
    return bill


def _set_lines(bill: VendorBill, lines: list[BillLineInput]) -> None:
    bill.lines.clear()
    for idx, line in enumerate(lines, start=1):
        bill.lines.append(
            VendorBillLine(
                account_id=line.account_id,
                line_number=idx,
                description=line.description,
                amount=line.amount,
            )
        )


# ─── Bill endpoints ───────────────────────────────────────────────────────────

@router.get("/bills", response_model=list[BillResponse])
async def list_bills(
    vendor_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(VendorBill)
        .where(VendorBill.organization_id == current_user.organization_id)
        .options(
            selectinload(VendorBill.lines),
            selectinload(VendorBill.payments),
        )
        .order_by(VendorBill.bill_date.desc(), VendorBill.created_at.desc())
    )
    if vendor_id:
        stmt = stmt.where(VendorBill.vendor_id == vendor_id)
    if status_filter:
        stmt = stmt.where(VendorBill.status == status_filter)
    result = await db.execute(stmt)
    return [_serialize_bill(b) for b in result.scalars().unique().all()]


@router.get("/bills/{bill_id}", response_model=BillResponse)
async def get_bill(
    bill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    bill = await _load_bill(db, bill_id, current_user.organization_id)
    return _serialize_bill(bill)


@router.post("/bills", response_model=BillResponse, status_code=status.HTTP_201_CREATED)
async def create_bill(
    payload: BillCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Capture a draft vendor bill with its expense-allocation lines."""
    org_id = current_user.organization_id
    await _get_vendor(db, payload.vendor_id, org_id)
    try:
        currency = svc.validate_currency(payload.currency)
        svc.validate_lines([line.model_dump() for line in payload.lines])
    except APError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    await _validate_accounts(db, {line.account_id for line in payload.lines}, org_id)

    bill = VendorBill(
        organization_id=org_id,
        vendor_id=payload.vendor_id,
        bill_number=payload.bill_number,
        bill_date=payload.bill_date,
        due_date=payload.due_date,
        currency=currency,
        memo=payload.memo,
        status="draft",
    )
    _set_lines(bill, payload.lines)
    bill.total_amount = svc.bill_total(bill)
    db.add(bill)
    await db.commit()
    bill = await _load_bill(db, bill.id, org_id)
    return _serialize_bill(bill)


@router.patch("/bills/{bill_id}", response_model=BillResponse)
async def update_bill(
    bill_id: uuid.UUID,
    payload: BillUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Edit a draft bill (header and/or lines) and re-total it."""
    org_id = current_user.organization_id
    bill = await _load_bill(db, bill_id, org_id)
    if bill.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft bill can be modified.",
        )

    data = payload.model_dump(exclude_unset=True)
    for field in ("bill_date", "due_date", "bill_number", "memo"):
        if field in data:
            setattr(bill, field, data[field])
    if "currency" in data:
        try:
            bill.currency = svc.validate_currency(data["currency"])
        except APError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    if payload.lines is not None:
        try:
            svc.validate_lines([line.model_dump() for line in payload.lines])
        except APError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        await _validate_accounts(db, {line.account_id for line in payload.lines}, org_id)
        _set_lines(bill, payload.lines)

    bill.total_amount = svc.bill_total(bill)
    await db.commit()
    bill = await _load_bill(db, bill.id, org_id)
    return _serialize_bill(bill)


@router.delete("/bills/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bill(
    bill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    bill = await _load_bill(db, bill_id, current_user.organization_id)
    if bill.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft bill can be deleted.",
        )
    await db.delete(bill)
    await db.commit()


@router.post("/bills/{bill_id}/finalize", response_model=BillResponse)
async def finalize_bill(
    bill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Lock a draft bill and post it to the GL (Dr expense / Cr Accounts Payable)."""
    org_id = current_user.organization_id
    bill = await _load_bill(db, bill_id, org_id)
    if bill.status == "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Bill is already finalized."
        )
    if bill.status == "void":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A void bill cannot be finalized."
        )
    if not bill.lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A bill must have at least one line before it can be finalized.",
        )

    bill.status = "finalized"
    bill.finalized_at = datetime.now(timezone.utc)
    bill.finalized_by_id = current_user.id
    bill.total_amount = svc.bill_total(bill)
    try:
        await svc.post_bill_to_gl(db, org_id, bill, posted_by_id=current_user.id)
    except APError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    bill = await _load_bill(db, bill.id, org_id)
    return _serialize_bill(bill)


@router.post("/bills/{bill_id}/void", response_model=BillResponse)
async def void_bill(
    bill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Void a finalized bill, reversing its GL entry. Paid bills cannot be voided."""
    org_id = current_user.organization_id
    bill = await _load_bill(db, bill_id, org_id)
    if bill.status != "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a finalized bill can be voided.",
        )
    if svc.amount_paid(bill) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A bill with payments cannot be voided; remove its payments first.",
        )
    await svc.remove_bill_entry(db, org_id, bill, commit=False)
    bill.journal_entry_id = None
    bill.status = "void"
    await db.commit()
    bill = await _load_bill(db, bill.id, org_id)
    return _serialize_bill(bill)


# ─── Payment endpoints ────────────────────────────────────────────────────────

@router.post(
    "/bills/{bill_id}/payments",
    response_model=BillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    bill_id: uuid.UUID,
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Record a payment against a finalized bill and post Dr AP / Cr Cash."""
    org_id = current_user.organization_id
    bill = await _load_bill(db, bill_id, org_id)
    if bill.status != "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payments can only be recorded against a finalized bill.",
        )
    amount = svc._q(payload.amount)
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payment amount must be greater than zero.",
        )
    if amount > svc.balance_due(bill):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payment exceeds the bill's outstanding balance.",
        )

    payment = VendorPayment(
        organization_id=org_id,
        bill_id=bill.id,
        payment_date=payload.payment_date,
        amount=amount,
        method=payload.method,
        reference=payload.reference,
        memo=payload.memo,
        created_by_id=current_user.id,
    )
    db.add(payment)
    await db.flush()
    try:
        await svc.post_payment_to_gl(db, org_id, payment, posted_by_id=current_user.id)
    except APError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    bill = await _load_bill(db, bill.id, org_id)
    return _serialize_bill(bill)


@router.delete("/payments/{payment_id}", response_model=BillResponse)
async def delete_payment(
    payment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Remove a payment and reverse its GL entry."""
    org_id = current_user.organization_id
    payment = (
        await db.execute(
            select(VendorPayment).where(
                VendorPayment.id == payment_id,
                VendorPayment.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    bill_id = payment.bill_id
    await svc.remove_payment_entry(db, org_id, payment, commit=False)
    await db.delete(payment)
    await db.commit()

    bill = await _load_bill(db, bill_id, org_id)
    return _serialize_bill(bill)

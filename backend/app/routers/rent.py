"""Rent collection & payments-in API router (Phase 2.3) — ``/api/v1/rent``.

Recurring rent charges, automated invoice generation and late fees, inbound
payments (ACH/card via the payment processor), and security-deposit tracking.
Everything posts through the shared general ledger by reusing the accounts-
receivable module: rent invoices are ``CustomerInvoice`` rows tagged
``source="rent"`` and appear in the AR aging report and receipt flow.

All endpoints are gated to the ``admin`` and ``accountant`` roles so inbound
money stays with finance staff, matching the AR/AP routers. Amounts are USD-only.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.customer_invoice import CustomerInvoice
from app.models.rent import (
    LATE_FEE_TYPES,
    RENT_CHARGE_TYPES,
    RENT_FREQUENCIES,
    RentCharge,
    SecurityDeposit,
)
from app.models.resident import ResidentLease
from app.models.user import User
from app.services import rent_service as svc
from app.services.rent_service import RentError

router = APIRouter()

# Finance staff only, matching the AR/AP routers.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class RentChargeCreate(BaseModel):
    resident_lease_id: uuid.UUID
    charge_type: str = "rent"
    description: str | None = None
    amount: Decimal
    frequency: str = "monthly"
    day_of_month: int = 1
    start_date: date | None = None
    end_date: date | None = None
    grace_days: int = 0
    late_fee_type: str = "none"
    late_fee_amount: Decimal | None = None
    revenue_account_code: str = "4000"
    active: bool = True


class RentChargeUpdate(BaseModel):
    charge_type: str | None = None
    description: str | None = None
    amount: Decimal | None = None
    frequency: str | None = None
    day_of_month: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    grace_days: int | None = None
    late_fee_type: str | None = None
    late_fee_amount: Decimal | None = None
    revenue_account_code: str | None = None
    active: bool | None = None


class RentChargeResponse(BaseModel):
    id: uuid.UUID
    resident_lease_id: uuid.UUID
    charge_type: str
    description: str | None
    amount: Decimal
    frequency: str
    day_of_month: int
    start_date: date | None
    end_date: date | None
    grace_days: int
    late_fee_type: str
    late_fee_amount: Decimal | None
    revenue_account_code: str
    currency: str
    active: bool
    last_billed_period: date | None

    class Config:
        from_attributes = True


class DepositCreate(BaseModel):
    resident_lease_id: uuid.UUID
    amount: Decimal
    held_date: date | None = None
    notes: str | None = None


class DepositReturn(BaseModel):
    returned_amount: Decimal = Decimal("0")
    forfeited_amount: Decimal = Decimal("0")
    returned_date: date | None = None


class DepositResponse(BaseModel):
    id: uuid.UUID
    resident_lease_id: uuid.UUID
    amount: Decimal
    held_date: date
    status: str
    returned_amount: Decimal
    forfeited_amount: Decimal
    returned_date: date | None
    currency: str
    notes: str | None

    class Config:
        from_attributes = True


class PaymentCreate(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal
    method: str = "ach"
    payment_token: str | None = None
    receipt_date: date | None = None
    reference: str | None = None


class PaymentResponse(BaseModel):
    receipt_id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    method: str | None
    captured: bool
    processor_status: str


class BillingRunResponse(BaseModel):
    generated: int
    invoice_ids: list[str]


class LateFeeRunResponse(BaseModel):
    assessed: int
    invoice_ids: list[str]


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_charge(db: AsyncSession, charge_id: uuid.UUID, org_id) -> RentCharge:
    charge = (
        await db.execute(
            select(RentCharge).where(
                RentCharge.id == charge_id,
                RentCharge.organization_id == org_id,
                RentCharge.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if charge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rent charge not found.")
    return charge


async def _validate_lease(db: AsyncSession, lease_id: uuid.UUID, org_id) -> None:
    lease = (
        await db.execute(
            select(ResidentLease.id).where(
                ResidentLease.id == lease_id,
                ResidentLease.organization_id == org_id,
            )
        )
    ).first()
    if lease is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resident lease not found.")


def _validate_enum(value: str, allowed: tuple[str, ...], field: str) -> None:
    if value not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid {field} '{value}'. Allowed: {', '.join(allowed)}.",
        )


# ─── Rent charges ─────────────────────────────────────────────────────────────

@router.get("/charges", response_model=list[RentChargeResponse])
async def list_charges(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    resident_lease_id: uuid.UUID | None = Query(None),
    active: bool | None = Query(None),
):
    stmt = select(RentCharge).where(
        RentCharge.organization_id == current_user.organization_id,
        RentCharge.is_deleted.is_(False),
    )
    if resident_lease_id is not None:
        stmt = stmt.where(RentCharge.resident_lease_id == resident_lease_id)
    if active is not None:
        stmt = stmt.where(RentCharge.active.is_(active))
    charges = (await db.execute(stmt.order_by(RentCharge.created_at))).scalars().all()
    return charges


@router.post("/charges", response_model=RentChargeResponse, status_code=status.HTTP_201_CREATED)
async def create_charge(
    payload: RentChargeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    _validate_enum(payload.charge_type, RENT_CHARGE_TYPES, "charge_type")
    _validate_enum(payload.frequency, RENT_FREQUENCIES, "frequency")
    _validate_enum(payload.late_fee_type, LATE_FEE_TYPES, "late_fee_type")
    if Decimal(str(payload.amount)) <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "amount must be greater than zero.")
    await _validate_lease(db, payload.resident_lease_id, current_user.organization_id)

    charge = RentCharge(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(charge)
    await db.commit()
    await db.refresh(charge)
    return charge


@router.patch("/charges/{charge_id}", response_model=RentChargeResponse)
async def update_charge(
    charge_id: uuid.UUID,
    payload: RentChargeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    charge = await _get_charge(db, charge_id, current_user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    if "charge_type" in data:
        _validate_enum(data["charge_type"], RENT_CHARGE_TYPES, "charge_type")
    if "frequency" in data:
        _validate_enum(data["frequency"], RENT_FREQUENCIES, "frequency")
    if "late_fee_type" in data:
        _validate_enum(data["late_fee_type"], LATE_FEE_TYPES, "late_fee_type")
    if "amount" in data and Decimal(str(data["amount"])) <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "amount must be greater than zero.")
    for field, value in data.items():
        setattr(charge, field, value)
    await db.commit()
    await db.refresh(charge)
    return charge


@router.delete("/charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_charge(
    charge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    charge = await _get_charge(db, charge_id, current_user.organization_id)
    charge.is_deleted = True
    charge.active = False
    await db.commit()


@router.post("/charges/{charge_id}/generate-invoice", response_model=BillingRunResponse)
async def generate_invoice(
    charge_id: uuid.UUID,
    period_start: date = Query(..., description="First-of-month period to bill."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    charge = await _get_charge(db, charge_id, current_user.organization_id)
    try:
        invoice = await svc.generate_rent_invoice(
            db, current_user.organization_id, charge,
            period_start.replace(day=1), posted_by_id=current_user.id,
        )
    except RentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    ids = [str(invoice.id)] if invoice is not None else []
    return {"generated": len(ids), "invoice_ids": ids}


# ─── Billing runs ─────────────────────────────────────────────────────────────

@router.post("/run-billing", response_model=BillingRunResponse)
async def run_billing(
    as_of: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    try:
        return await svc.run_recurring_billing(
            db, current_user.organization_id, as_of=as_of, posted_by_id=current_user.id
        )
    except RentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.post("/apply-late-fees", response_model=LateFeeRunResponse)
async def apply_late_fees(
    as_of: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    try:
        return await svc.apply_late_fees(
            db, current_user.organization_id, as_of=as_of, posted_by_id=current_user.id
        )
    except RentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


# ─── Payments ─────────────────────────────────────────────────────────────────

@router.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_payment(
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    invoice = (
        await db.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.id == payload.invoice_id,
                CustomerInvoice.organization_id == current_user.organization_id,
            )
            .options(selectinload(CustomerInvoice.receipts))
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    try:
        result = await svc.record_rent_payment(
            db,
            current_user.organization_id,
            invoice,
            payload.amount,
            method=payload.method,
            payment_token=payload.payment_token,
            receipt_date=payload.receipt_date,
            reference=payload.reference,
            created_by_id=current_user.id,
        )
    except RentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    receipt = result["receipt"]
    return {
        "receipt_id": receipt.id,
        "invoice_id": invoice.id,
        "amount": receipt.amount,
        "method": receipt.method,
        "captured": result["captured"],
        "processor_status": result["processor_status"],
    }


# ─── Security deposits ────────────────────────────────────────────────────────

@router.get("/deposits", response_model=list[DepositResponse])
async def list_deposits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    resident_lease_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
):
    stmt = select(SecurityDeposit).where(
        SecurityDeposit.organization_id == current_user.organization_id,
        SecurityDeposit.is_deleted.is_(False),
    )
    if resident_lease_id is not None:
        stmt = stmt.where(SecurityDeposit.resident_lease_id == resident_lease_id)
    if status_filter is not None:
        stmt = stmt.where(SecurityDeposit.status == status_filter)
    deposits = (await db.execute(stmt.order_by(SecurityDeposit.held_date))).scalars().all()
    return deposits


@router.post("/deposits", response_model=DepositResponse, status_code=status.HTTP_201_CREATED)
async def create_deposit(
    payload: DepositCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    try:
        deposit = await svc.record_deposit(
            db,
            current_user.organization_id,
            resident_lease_id=payload.resident_lease_id,
            amount=payload.amount,
            held_date=payload.held_date,
            notes=payload.notes,
            posted_by_id=current_user.id,
        )
    except RentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return deposit


@router.post("/deposits/{deposit_id}/return", response_model=DepositResponse)
async def return_deposit(
    deposit_id: uuid.UUID,
    payload: DepositReturn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    deposit = (
        await db.execute(
            select(SecurityDeposit).where(
                SecurityDeposit.id == deposit_id,
                SecurityDeposit.organization_id == current_user.organization_id,
                SecurityDeposit.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if deposit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Security deposit not found.")
    try:
        deposit = await svc.return_deposit(
            db,
            current_user.organization_id,
            deposit,
            returned_amount=payload.returned_amount,
            forfeited_amount=payload.forfeited_amount,
            returned_date=payload.returned_date,
            posted_by_id=current_user.id,
        )
    except RentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return deposit

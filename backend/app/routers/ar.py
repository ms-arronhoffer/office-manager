"""Accounts-receivable-lite API router (Phase 1.1) — `/api/v1/ar`.

Customer invoices and the cash received against them, posting into the
audit-grade general ledger. All endpoints are gated to the ``admin`` and
``accountant`` roles so finance data stays with finance staff. This mirrors the
accounts-payable router (``/api/v1/ap``) on the sell side.

Workflow:
  1. ``POST /customers`` registers an AR counterparty.
  2. ``POST /invoices`` captures a draft invoice with one or more
     revenue-allocation lines (fully editable).
  3. ``PATCH`` / ``DELETE`` edit or remove a draft.
  4. ``POST /invoices/{id}/finalize`` locks the invoice and posts
     ``Dr Accounts Receivable / Cr revenue`` to the GL.
  5. ``POST /invoices/{id}/receipts`` records cash received, posting
     ``Dr Cash / Cr Accounts Receivable``; the invoice's open/partial/paid
     status is derived from its receipts.
  6. ``POST /invoices/{id}/void`` reverses an unpaid finalized invoice's GL entry.
  7. ``GET /aging`` returns an AR aging report over open invoices.
  8. ``POST /invoices/from-cam/{reconciliation_id}`` drafts an invoice from a
     finalized CAM true-up.

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
from app.models.cam_reconciliation import CamReconciliation
from app.models.customer_invoice import (
    Customer,
    CustomerInvoice,
    CustomerInvoiceLine,
    CustomerReceipt,
)
from app.models.general_ledger import GLAccount
from app.models.user import User
from app.services import ar_service as svc
from app.services.ar_service import ARError

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    notes: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    notes: str | None = None


class CustomerResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceLineInput(BaseModel):
    account_id: uuid.UUID
    amount: Decimal
    description: str | None = None


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_date: date
    due_date: date | None = None
    invoice_number: str | None = None
    currency: str = "USD"
    memo: str | None = None
    lines: list[InvoiceLineInput]


class InvoiceUpdate(BaseModel):
    invoice_date: date | None = None
    due_date: date | None = None
    invoice_number: str | None = None
    currency: str | None = None
    memo: str | None = None
    lines: list[InvoiceLineInput] | None = None


class InvoiceLineResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    line_number: int
    description: str | None
    amount: Decimal

    model_config = {"from_attributes": True}


class ReceiptCreate(BaseModel):
    receipt_date: date
    amount: Decimal
    method: str | None = None
    reference: str | None = None
    memo: str | None = None


class ReceiptResponse(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    receipt_date: date
    amount: Decimal
    method: str | None
    reference: str | None
    memo: str | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    customer_id: uuid.UUID
    invoice_number: str | None
    invoice_date: date
    due_date: date | None
    currency: str
    memo: str | None
    total_amount: Decimal
    amount_received: Decimal
    balance_due: Decimal
    receipt_state: str
    status: str
    source: str | None
    source_ref: str | None
    finalized_at: datetime | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    lines: list[InvoiceLineResponse]
    receipts: list[ReceiptResponse]


class AgingInvoice(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str | None
    invoice_date: date
    due_date: date | None
    balance_due: Decimal
    bucket: str


class AgingCustomerRow(BaseModel):
    customer_id: uuid.UUID
    customer_name: str | None
    buckets: dict[str, Decimal]
    total: Decimal
    invoices: list[AgingInvoice]


class AgingReport(BaseModel):
    as_of: date
    buckets: list[str]
    customers: list[AgingCustomerRow]
    totals: dict[str, Decimal]
    grand_total: Decimal


# ─── Helpers ────────────────────────────────────────────────────────────────

def _serialize_invoice(invoice: CustomerInvoice) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        organization_id=invoice.organization_id,
        customer_id=invoice.customer_id,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        memo=invoice.memo,
        total_amount=svc.invoice_total(invoice),
        amount_received=svc.amount_received(invoice),
        balance_due=svc.balance_due(invoice),
        receipt_state=svc.receipt_state(invoice),
        status=invoice.status,
        source=invoice.source,
        source_ref=invoice.source_ref,
        finalized_at=invoice.finalized_at,
        journal_entry_id=invoice.journal_entry_id,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        lines=[InvoiceLineResponse.model_validate(line) for line in invoice.lines],
        receipts=[ReceiptResponse.model_validate(r) for r in invoice.receipts],
    )


async def _get_customer(db: AsyncSession, customer_id: uuid.UUID, org_id) -> Customer:
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.organization_id == org_id,
                Customer.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


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


async def _load_invoice(db: AsyncSession, invoice_id: uuid.UUID, org_id) -> CustomerInvoice:
    # Detach cached instances so the reload builds fresh objects with all
    # columns/relationships populated (derived totals reflect the latest writes).
    db.expunge_all()
    invoice = await svc.get_invoice(db, invoice_id, org_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


def _set_lines(invoice: CustomerInvoice, lines: list[InvoiceLineInput]) -> None:
    invoice.lines.clear()
    for idx, line in enumerate(lines, start=1):
        invoice.lines.append(
            CustomerInvoiceLine(
                account_id=line.account_id,
                line_number=idx,
                description=line.description,
                amount=line.amount,
            )
        )


# ─── Customer endpoints ───────────────────────────────────────────────────────

@router.get("/customers", response_model=list[CustomerResponse])
async def list_customers(
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(Customer)
        .where(
            Customer.organization_id == current_user.organization_id,
            Customer.is_deleted.is_(False),
        )
        .order_by(Customer.name)
    )
    if q:
        stmt = stmt.where(Customer.name.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    return [CustomerResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/customers", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    customer = Customer(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return CustomerResponse.model_validate(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    customer = await _get_customer(db, customer_id, current_user.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    await db.commit()
    await db.refresh(customer)
    return CustomerResponse.model_validate(customer)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    customer = await _get_customer(db, customer_id, current_user.organization_id)
    has_invoices = (
        await db.execute(
            select(CustomerInvoice.id).where(CustomerInvoice.customer_id == customer.id).limit(1)
        )
    ).first()
    if has_invoices:
        # Preserve financial history: soft-delete a customer that has invoices.
        customer.is_deleted = True
        customer.deleted_at = datetime.now(timezone.utc)
    else:
        await db.delete(customer)
    await db.commit()


# ─── Aging report ─────────────────────────────────────────────────────────────

@router.get("/aging", response_model=AgingReport)
async def get_aging(
    as_of: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """AR aging report over open (unpaid) finalized invoices."""
    data = await svc.aging_report(db, current_user.organization_id, as_of=as_of)
    return AgingReport(**data)


# ─── Invoice endpoints ────────────────────────────────────────────────────────

@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    customer_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    open_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(CustomerInvoice)
        .where(CustomerInvoice.organization_id == current_user.organization_id)
        .options(
            selectinload(CustomerInvoice.lines),
            selectinload(CustomerInvoice.receipts),
        )
        .order_by(CustomerInvoice.invoice_date.desc(), CustomerInvoice.created_at.desc())
    )
    if customer_id:
        stmt = stmt.where(CustomerInvoice.customer_id == customer_id)
    if status_filter:
        stmt = stmt.where(CustomerInvoice.status == status_filter)
    result = await db.execute(stmt)
    invoices = result.scalars().unique().all()
    serialized = [_serialize_invoice(i) for i in invoices]
    if open_only:
        # Open-invoice tracking: finalized invoices with a positive balance.
        serialized = [
            i for i in serialized
            if i.status == "finalized" and i.balance_due > 0
        ]
    return serialized


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    invoice = await _load_invoice(db, invoice_id, current_user.organization_id)
    return _serialize_invoice(invoice)


@router.post("/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Capture a draft customer invoice with its revenue-allocation lines."""
    org_id = current_user.organization_id
    await _get_customer(db, payload.customer_id, org_id)
    try:
        currency = svc.validate_currency(payload.currency)
        svc.validate_lines([line.model_dump() for line in payload.lines])
    except ARError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    await _validate_accounts(db, {line.account_id for line in payload.lines}, org_id)

    invoice = CustomerInvoice(
        organization_id=org_id,
        customer_id=payload.customer_id,
        invoice_number=payload.invoice_number,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        currency=currency,
        memo=payload.memo,
        status="draft",
    )
    _set_lines(invoice, payload.lines)
    invoice.total_amount = svc.invoice_total(invoice)
    db.add(invoice)
    await db.commit()
    invoice = await _load_invoice(db, invoice.id, org_id)
    return _serialize_invoice(invoice)


@router.post(
    "/invoices/from-cam/{reconciliation_id}",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice_from_cam(
    reconciliation_id: uuid.UUID,
    customer_id: uuid.UUID = Query(...),
    invoice_date: date | None = Query(default=None),
    due_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Draft an AR invoice from a finalized CAM true-up balance.

    Turns a CAM reconciliation's tenant true-up into a formal, GL-postable
    invoice rather than leaving it as a bare number. The invoice is created in
    ``draft`` status so it can be reviewed before finalizing.
    """
    from app.services import gl_service

    org_id = current_user.organization_id
    await _get_customer(db, customer_id, org_id)

    recon = (
        await db.execute(
            select(CamReconciliation).where(
                CamReconciliation.id == reconciliation_id,
                CamReconciliation.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")
    if recon.status != "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a finalized reconciliation can be invoiced.",
        )

    await gl_service.seed_default_accounts(db, org_id)
    await gl_service.ensure_accounts(db, org_id, svc.AR_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, org_id)
    try:
        line_dicts, memo = svc.build_invoice_lines_from_cam(recon, account_map)
    except ARError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    invoice = CustomerInvoice(
        organization_id=org_id,
        customer_id=customer_id,
        invoice_date=invoice_date or date.today(),
        due_date=due_date,
        currency="USD",
        memo=memo,
        status="draft",
        source="cam",
        source_ref=str(recon.id),
    )
    _set_lines(
        invoice,
        [InvoiceLineInput(**line) for line in line_dicts],
    )
    invoice.total_amount = svc.invoice_total(invoice)
    db.add(invoice)
    await db.commit()
    invoice = await _load_invoice(db, invoice.id, org_id)
    return _serialize_invoice(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Edit a draft invoice (header and/or lines) and re-total it."""
    org_id = current_user.organization_id
    invoice = await _load_invoice(db, invoice_id, org_id)
    if invoice.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft invoice can be modified.",
        )

    data = payload.model_dump(exclude_unset=True)
    for field in ("invoice_date", "due_date", "invoice_number", "memo"):
        if field in data:
            setattr(invoice, field, data[field])
    if "currency" in data:
        try:
            invoice.currency = svc.validate_currency(data["currency"])
        except ARError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    if payload.lines is not None:
        try:
            svc.validate_lines([line.model_dump() for line in payload.lines])
        except ARError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        await _validate_accounts(db, {line.account_id for line in payload.lines}, org_id)
        _set_lines(invoice, payload.lines)

    invoice.total_amount = svc.invoice_total(invoice)
    await db.commit()
    invoice = await _load_invoice(db, invoice.id, org_id)
    return _serialize_invoice(invoice)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    invoice = await _load_invoice(db, invoice_id, current_user.organization_id)
    if invoice.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft invoice can be deleted.",
        )
    await db.delete(invoice)
    await db.commit()


@router.post("/invoices/{invoice_id}/finalize", response_model=InvoiceResponse)
async def finalize_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Lock a draft invoice and post it to the GL (Dr AR / Cr revenue)."""
    org_id = current_user.organization_id
    invoice = await _load_invoice(db, invoice_id, org_id)
    if invoice.status == "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Invoice is already finalized."
        )
    if invoice.status == "void":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A void invoice cannot be finalized."
        )
    if not invoice.lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An invoice must have at least one line before it can be finalized.",
        )

    invoice.status = "finalized"
    invoice.finalized_at = datetime.now(timezone.utc)
    invoice.finalized_by_id = current_user.id
    invoice.total_amount = svc.invoice_total(invoice)
    try:
        await svc.post_invoice_to_gl(db, org_id, invoice, posted_by_id=current_user.id)
    except ARError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    invoice = await _load_invoice(db, invoice.id, org_id)
    return _serialize_invoice(invoice)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceResponse)
async def void_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Void a finalized invoice, reversing its GL entry. Paid invoices cannot be voided."""
    org_id = current_user.organization_id
    invoice = await _load_invoice(db, invoice_id, org_id)
    if invoice.status != "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a finalized invoice can be voided.",
        )
    if svc.amount_received(invoice) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invoice with receipts cannot be voided; remove its receipts first.",
        )
    await svc.remove_invoice_entry(db, org_id, invoice, commit=False)
    invoice.journal_entry_id = None
    invoice.status = "void"
    await db.commit()
    invoice = await _load_invoice(db, invoice.id, org_id)
    return _serialize_invoice(invoice)


# ─── Receipt endpoints ────────────────────────────────────────────────────────

@router.post(
    "/invoices/{invoice_id}/receipts",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_receipt(
    invoice_id: uuid.UUID,
    payload: ReceiptCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Record cash received against a finalized invoice and post Dr Cash / Cr AR."""
    org_id = current_user.organization_id
    invoice = await _load_invoice(db, invoice_id, org_id)
    if invoice.status != "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receipts can only be recorded against a finalized invoice.",
        )
    amount = svc._q(payload.amount)
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt amount must be greater than zero.",
        )
    if amount > svc.balance_due(invoice):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt exceeds the invoice's outstanding balance.",
        )

    receipt = CustomerReceipt(
        organization_id=org_id,
        invoice_id=invoice.id,
        receipt_date=payload.receipt_date,
        amount=amount,
        method=payload.method,
        reference=payload.reference,
        memo=payload.memo,
        created_by_id=current_user.id,
    )
    db.add(receipt)
    await db.flush()
    try:
        await svc.post_receipt_to_gl(db, org_id, receipt, posted_by_id=current_user.id)
    except ARError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    invoice = await _load_invoice(db, invoice.id, org_id)
    return _serialize_invoice(invoice)


@router.delete("/receipts/{receipt_id}", response_model=InvoiceResponse)
async def delete_receipt(
    receipt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Remove a receipt and reverse its GL entry."""
    org_id = current_user.organization_id
    receipt = (
        await db.execute(
            select(CustomerReceipt).where(
                CustomerReceipt.id == receipt_id,
                CustomerReceipt.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")

    invoice_id = receipt.invoice_id
    await svc.remove_receipt_entry(db, org_id, receipt, commit=False)
    await db.delete(receipt)
    await db.commit()

    invoice = await _load_invoice(db, invoice_id, org_id)
    return _serialize_invoice(invoice)

"""Procurement API — ``/api/v1/procurement``.

Drives the controlled path from a spend request to an approved commitment:

  1. ``POST /requisitions`` captures a costed request as a draft.
  2. ``POST /requisitions/{id}/quotes`` records competing vendor bids, and
     ``POST /quotes/{id}/select`` picks the winner (with a justification when
     the winner is not the lowest bid).
  3. ``POST /requisitions/{id}/submit`` routes it for a second signature and
     ``/approve`` or ``/reject`` completes the review.
  4. ``POST /requisitions/{id}/purchase-order`` issues the commitment once the
     bidding rules are satisfied.
  5. ``POST /purchase-orders/{id}/receipts`` confirms delivery, which is what
     later unlocks the three-way match when the vendor's bill arrives.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.procurement import (
    PO_OPEN_STATUSES,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseRequisition,
    ReceiptLine,
    RequisitionLine,
    VendorQuote,
)
from app.models.user import User
from app.models.vendor import Vendor
from app.services import approval_service, procurement_service
from app.services.approval_service import ApprovalError
from app.services.procurement_service import ProcurementError, line_amount, q

router = APIRouter()

# Requesting spend is a normal operational act; approving and issuing orders is
# restricted to finance and administrators by the checks on those endpoints.
BuyerUser = require_role("admin", "accountant", "editor")
ApproverUser = require_role("admin", "accountant")


# ─── Schemas ────────────────────────────────────────────────────────────────

class RequisitionLineInput(BaseModel):
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    account_id: uuid.UUID | None = None


class RequisitionCreate(BaseModel):
    title: str
    description: str | None = None
    office_id: uuid.UUID | None = None
    category: str | None = None
    needed_by: date | None = None
    requisition_number: str | None = None
    lines: list[RequisitionLineInput] = Field(default_factory=list)


class RequisitionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    office_id: uuid.UUID | None = None
    category: str | None = None
    needed_by: date | None = None
    requisition_number: str | None = None
    lines: list[RequisitionLineInput] | None = None


class RequisitionLineResponse(BaseModel):
    id: uuid.UUID
    line_number: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    account_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class QuoteCreate(BaseModel):
    vendor_id: uuid.UUID
    amount: Decimal
    quote_date: date | None = None
    valid_until: date | None = None
    reference: str | None = None
    notes: str | None = None


class QuoteSelect(BaseModel):
    selection_reason: str | None = None


class QuoteResponse(BaseModel):
    id: uuid.UUID
    requisition_id: uuid.UUID
    vendor_id: uuid.UUID
    amount: Decimal
    quote_date: date | None
    valid_until: date | None
    reference: str | None
    notes: str | None
    is_selected: bool
    selection_reason: str | None
    selected_at: datetime | None

    model_config = {"from_attributes": True}


class RequisitionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    requisition_number: str | None
    title: str
    description: str | None
    office_id: uuid.UUID | None
    category: str | None
    needed_by: date | None
    status: str
    estimated_total: Decimal
    requested_by_id: uuid.UUID | None
    ordered_at: datetime | None
    approval_status: str
    prepared_by_id: uuid.UUID | None
    submitted_at: datetime | None
    submitted_by_id: uuid.UUID | None
    approved_at: datetime | None
    approved_by_id: uuid.UUID | None
    rejected_at: datetime | None
    rejected_by_id: uuid.UUID | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[RequisitionLineResponse]
    quotes: list[QuoteResponse]


class RejectInput(BaseModel):
    reason: str | None = None


class PurchaseOrderCreate(BaseModel):
    vendor_id: uuid.UUID | None = None
    order_date: date | None = None
    expected_date: date | None = None
    po_number: str | None = None
    memo: str | None = None
    match_tolerance_percent: Decimal | None = None


class PurchaseOrderLineResponse(BaseModel):
    id: uuid.UUID
    line_number: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    quantity_received: Decimal
    account_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class ReceiptLineInput(BaseModel):
    purchase_order_line_id: uuid.UUID
    quantity: Decimal


class ReceiptCreate(BaseModel):
    received_on: date | None = None
    notes: str | None = None
    lines: list[ReceiptLineInput]


class ReceiptLineResponse(BaseModel):
    id: uuid.UUID
    purchase_order_line_id: uuid.UUID
    quantity: Decimal

    model_config = {"from_attributes": True}


class ReceiptResponse(BaseModel):
    id: uuid.UUID
    received_on: date
    received_by_id: uuid.UUID | None
    notes: str | None
    lines: list[ReceiptLineResponse]

    model_config = {"from_attributes": True}


class PurchaseOrderResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    requisition_id: uuid.UUID | None
    vendor_id: uuid.UUID
    po_number: str | None
    order_date: date
    expected_date: date | None
    status: str
    total_amount: Decimal
    match_tolerance_percent: Decimal
    memo: str | None
    issued_by_id: uuid.UUID | None
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseOrderLineResponse]
    receipts: list[ReceiptResponse]


# ─── Helpers ────────────────────────────────────────────────────────────────

def _serialize_requisition(req: PurchaseRequisition) -> RequisitionResponse:
    return RequisitionResponse(
        id=req.id,
        organization_id=req.organization_id,
        requisition_number=req.requisition_number,
        title=req.title,
        description=req.description,
        office_id=req.office_id,
        category=req.category,
        needed_by=req.needed_by,
        status=req.status,
        estimated_total=q(req.estimated_total),
        requested_by_id=req.requested_by_id,
        ordered_at=req.ordered_at,
        created_at=req.created_at,
        updated_at=req.updated_at,
        lines=[RequisitionLineResponse.model_validate(line) for line in req.lines],
        quotes=[QuoteResponse.model_validate(quote) for quote in req.quotes],
        **approval_service.serialize(req),
    )


def _serialize_order(order: PurchaseOrder) -> PurchaseOrderResponse:
    return PurchaseOrderResponse(
        id=order.id,
        organization_id=order.organization_id,
        requisition_id=order.requisition_id,
        vendor_id=order.vendor_id,
        po_number=order.po_number,
        order_date=order.order_date,
        expected_date=order.expected_date,
        status=order.status,
        total_amount=q(order.total_amount),
        match_tolerance_percent=Decimal(str(order.match_tolerance_percent or 0)),
        memo=order.memo,
        issued_by_id=order.issued_by_id,
        issued_at=order.issued_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        lines=[PurchaseOrderLineResponse.model_validate(line) for line in order.lines],
        receipts=[ReceiptResponse.model_validate(r) for r in order.receipts],
    )


async def _load_requisition(
    db: AsyncSession, requisition_id: uuid.UUID, org_id
) -> PurchaseRequisition:
    req = (
        await db.execute(
            select(PurchaseRequisition)
            .where(
                PurchaseRequisition.id == requisition_id,
                PurchaseRequisition.organization_id == org_id,
                PurchaseRequisition.is_deleted.is_(False),
            )
            .options(
                selectinload(PurchaseRequisition.lines),
                selectinload(PurchaseRequisition.quotes),
            )
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found"
        )
    return req


async def _load_order(db: AsyncSession, order_id: uuid.UUID, org_id) -> PurchaseOrder:
    order = (
        await db.execute(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.id == order_id,
                PurchaseOrder.organization_id == org_id,
            )
            .options(
                selectinload(PurchaseOrder.lines),
                selectinload(PurchaseOrder.receipts).selectinload(
                    PurchaseOrderReceipt.lines
                ),
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found"
        )
    return order


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


def _apply_lines(req: PurchaseRequisition, lines: list[RequisitionLineInput]) -> None:
    req.lines.clear()
    for idx, line in enumerate(lines, start=1):
        req.lines.append(
            RequisitionLine(
                line_number=idx,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line_amount(line.quantity, line.unit_price),
                account_id=line.account_id,
            )
        )
    req.estimated_total = q(
        sum((line_amount(l.quantity, l.unit_price) for l in lines), Decimal("0"))
    )


# ─── Requisitions ─────────────────────────────────────────────────────────────

@router.get("/requisitions", response_model=list[RequisitionResponse])
async def list_requisitions(
    status_filter: str | None = Query(default=None, alias="status"),
    approval_status: str | None = Query(default=None),
    office_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    stmt = (
        select(PurchaseRequisition)
        .where(
            PurchaseRequisition.organization_id == current_user.organization_id,
            PurchaseRequisition.is_deleted.is_(False),
        )
        .options(
            selectinload(PurchaseRequisition.lines),
            selectinload(PurchaseRequisition.quotes),
        )
        .order_by(PurchaseRequisition.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(PurchaseRequisition.status == status_filter)
    if approval_status:
        stmt = stmt.where(PurchaseRequisition.approval_status == approval_status)
    if office_id:
        stmt = stmt.where(PurchaseRequisition.office_id == office_id)
    result = await db.execute(stmt)
    return [_serialize_requisition(r) for r in result.scalars().unique().all()]


@router.get("/requisitions/{requisition_id}", response_model=RequisitionResponse)
async def get_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    req = await _load_requisition(db, requisition_id, current_user.organization_id)
    return _serialize_requisition(req)


@router.post(
    "/requisitions",
    response_model=RequisitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_requisition(
    payload: RequisitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    org_id = current_user.organization_id
    req = PurchaseRequisition(
        organization_id=org_id,
        requisition_number=payload.requisition_number,
        title=payload.title,
        description=payload.description,
        office_id=payload.office_id,
        category=payload.category,
        needed_by=payload.needed_by,
        status="draft",
        requested_by_id=current_user.id,
    )
    _apply_lines(req, payload.lines)
    await approval_service.initialize(
        db,
        req,
        organization_id=org_id,
        amount=req.estimated_total,
        prepared_by=current_user,
    )
    db.add(req)
    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


@router.patch("/requisitions/{requisition_id}", response_model=RequisitionResponse)
async def update_requisition(
    requisition_id: uuid.UUID,
    payload: RequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    org_id = current_user.organization_id
    req = await _load_requisition(db, requisition_id, org_id)
    if req.status not in ("draft", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft or rejected requisition can be modified.",
        )
    data = payload.model_dump(exclude_unset=True)
    for field in (
        "title",
        "description",
        "office_id",
        "category",
        "needed_by",
        "requisition_number",
    ):
        if field in data:
            setattr(req, field, data[field])
    if payload.lines is not None:
        _apply_lines(req, payload.lines)

    req.status = "draft"
    await approval_service.initialize(
        db,
        req,
        organization_id=org_id,
        amount=req.estimated_total,
        prepared_by=current_user,
    )
    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


@router.delete("/requisitions/{requisition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    req = await _load_requisition(db, requisition_id, current_user.organization_id)
    if req.status == "ordered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A requisition that has been ordered cannot be deleted.",
        )
    req.is_deleted = True
    await db.commit()


@router.post("/requisitions/{requisition_id}/submit", response_model=RequisitionResponse)
async def submit_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    org_id = current_user.organization_id
    req = await _load_requisition(db, requisition_id, org_id)
    if req.status not in ("draft", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft or rejected requisition can be submitted.",
        )
    if not req.lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Add at least one line before submitting a requisition.",
        )
    try:
        await approval_service.submit(
            db,
            req,
            organization_id=org_id,
            amount=req.estimated_total,
            user=current_user,
        )
    except ApprovalError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    req.status = "submitted"
    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


@router.post("/requisitions/{requisition_id}/approve", response_model=RequisitionResponse)
async def approve_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(ApproverUser),
):
    org_id = current_user.organization_id
    req = await _load_requisition(db, requisition_id, org_id)
    try:
        approval_service.approve(req, user=current_user)
    except ApprovalError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    req.status = "approved"
    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


@router.post("/requisitions/{requisition_id}/reject", response_model=RequisitionResponse)
async def reject_requisition(
    requisition_id: uuid.UUID,
    payload: RejectInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(ApproverUser),
):
    org_id = current_user.organization_id
    req = await _load_requisition(db, requisition_id, org_id)
    try:
        approval_service.reject(req, user=current_user, reason=payload.reason)
    except ApprovalError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    req.status = "rejected"
    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


# ─── Vendor quotes (competitive bids) ─────────────────────────────────────────

@router.post(
    "/requisitions/{requisition_id}/quotes",
    response_model=RequisitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_quote(
    requisition_id: uuid.UUID,
    payload: QuoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    org_id = current_user.organization_id
    req = await _load_requisition(db, requisition_id, org_id)
    if req.status == "ordered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This requisition has already been ordered.",
        )
    await _get_vendor(db, payload.vendor_id, org_id)
    if any(quote.vendor_id == payload.vendor_id for quote in req.quotes):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A quote from this vendor is already recorded.",
        )
    db.add(
        VendorQuote(
            requisition_id=req.id,
            vendor_id=payload.vendor_id,
            amount=payload.amount,
            quote_date=payload.quote_date,
            valid_until=payload.valid_until,
            reference=payload.reference,
            notes=payload.notes,
        )
    )
    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


@router.post("/quotes/{quote_id}/select", response_model=RequisitionResponse)
async def select_quote(
    quote_id: uuid.UUID,
    payload: QuoteSelect,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    """Pick the winning bid, recording who chose it and why."""
    org_id = current_user.organization_id
    quote = (
        await db.execute(select(VendorQuote).where(VendorQuote.id == quote_id))
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    req = await _load_requisition(db, quote.requisition_id, org_id)
    if req.status == "ordered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This requisition has already been ordered.",
        )

    for other in req.quotes:
        other.is_selected = other.id == quote_id
        if other.id != quote_id:
            other.selection_reason = None
            other.selected_by_id = None
            other.selected_at = None
    selected = next(qt for qt in req.quotes if qt.id == quote_id)
    selected.selection_reason = payload.selection_reason
    selected.selected_by_id = current_user.id
    selected.selected_at = datetime.now(timezone.utc)

    try:
        await procurement_service.assert_bids_sufficient(db, req)
    except ProcurementError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    await db.commit()
    req = await _load_requisition(db, req.id, org_id)
    return _serialize_requisition(req)


@router.delete("/quotes/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quote(
    quote_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    quote = (
        await db.execute(select(VendorQuote).where(VendorQuote.id == quote_id))
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    # Confirms the quote belongs to the caller's organization.
    await _load_requisition(db, quote.requisition_id, current_user.organization_id)
    await db.delete(quote)
    await db.commit()


# ─── Purchase orders ──────────────────────────────────────────────────────────

@router.post(
    "/requisitions/{requisition_id}/purchase-order",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_purchase_order(
    requisition_id: uuid.UUID,
    payload: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(ApproverUser),
):
    """Commit approved spend to a vendor once the bidding rules are satisfied."""
    org_id = current_user.organization_id
    req = await _load_requisition(db, requisition_id, org_id)

    if req.status == "ordered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A purchase order has already been issued for this requisition.",
        )
    try:
        approval_service.assert_postable(req, user=current_user)
    except ApprovalError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if req.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an approved requisition can become a purchase order.",
        )
    try:
        await procurement_service.assert_bids_sufficient(db, req)
    except ProcurementError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    selected = next((qt for qt in req.quotes if qt.is_selected), None)
    vendor_id = payload.vendor_id or (selected.vendor_id if selected else None)
    if vendor_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select a winning quote or supply a vendor for the purchase order.",
        )
    await _get_vendor(db, vendor_id, org_id)
    if selected and payload.vendor_id and payload.vendor_id != selected.vendor_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The purchase order vendor must match the selected quote.",
        )

    order = PurchaseOrder(
        organization_id=org_id,
        requisition_id=req.id,
        vendor_id=vendor_id,
        po_number=payload.po_number,
        order_date=payload.order_date or date.today(),
        expected_date=payload.expected_date or req.needed_by,
        status="issued",
        memo=payload.memo,
        issued_by_id=current_user.id,
        issued_at=datetime.now(timezone.utc),
    )
    if payload.match_tolerance_percent is not None:
        order.match_tolerance_percent = payload.match_tolerance_percent

    for idx, line in enumerate(req.lines, start=1):
        order.lines.append(
            PurchaseOrderLine(
                line_number=idx,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=q(line.amount),
                account_id=line.account_id,
            )
        )
    # The winning bid, not the estimate, is what the vendor is being committed to.
    order.total_amount = (
        q(selected.amount)
        if selected
        else q(sum((q(l.amount) for l in order.lines), Decimal("0")))
    )

    req.status = "ordered"
    req.ordered_at = datetime.now(timezone.utc)
    db.add(order)
    await db.commit()
    order = await _load_order(db, order.id, org_id)
    return _serialize_order(order)


@router.get("/purchase-orders", response_model=list[PurchaseOrderResponse])
async def list_purchase_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    vendor_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    stmt = (
        select(PurchaseOrder)
        .where(PurchaseOrder.organization_id == current_user.organization_id)
        .options(
            selectinload(PurchaseOrder.lines),
            selectinload(PurchaseOrder.receipts).selectinload(PurchaseOrderReceipt.lines),
        )
        .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(PurchaseOrder.status == status_filter)
    if vendor_id:
        stmt = stmt.where(PurchaseOrder.vendor_id == vendor_id)
    result = await db.execute(stmt)
    return [_serialize_order(o) for o in result.scalars().unique().all()]


@router.get("/purchase-orders/{order_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    order = await _load_order(db, order_id, current_user.organization_id)
    return _serialize_order(order)


@router.post(
    "/purchase-orders/{order_id}/receipts",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_receipt(
    order_id: uuid.UUID,
    payload: ReceiptCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(BuyerUser),
):
    """Confirm delivery, which is what later unlocks the three-way match."""
    org_id = current_user.organization_id
    order = await _load_order(db, order_id, org_id)
    if order.status not in PO_OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Purchase order is {order.status} and cannot be received against.",
        )
    if not payload.lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A receipt must record at least one line.",
        )

    by_id = {line.id: line for line in order.lines}
    receipt = PurchaseOrderReceipt(
        purchase_order_id=order.id,
        received_on=payload.received_on or date.today(),
        received_by_id=current_user.id,
        notes=payload.notes,
    )
    for entry in payload.lines:
        po_line = by_id.get(entry.purchase_order_line_id)
        if po_line is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Receipt line does not belong to this purchase order.",
            )
        if q(entry.quantity) <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Received quantity must be greater than zero.",
            )
        already = q(po_line.quantity_received)
        if already + q(entry.quantity) > q(po_line.quantity):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Receiving {entry.quantity} would exceed the ordered quantity "
                    f"for line {po_line.line_number}."
                ),
            )
        po_line.quantity_received = already + q(entry.quantity)
        receipt.lines.append(
            ReceiptLine(
                purchase_order_line_id=po_line.id,
                quantity=q(entry.quantity),
            )
        )

    db.add(receipt)
    order.status = procurement_service.recompute_status(order)
    await db.commit()
    order = await _load_order(db, order.id, org_id)
    return _serialize_order(order)


@router.post("/purchase-orders/{order_id}/close", response_model=PurchaseOrderResponse)
async def close_purchase_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(ApproverUser),
):
    org_id = current_user.organization_id
    order = await _load_order(db, order_id, org_id)
    if order.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cancelled purchase order cannot be closed.",
        )
    order.status = "closed"
    order.closed_at = datetime.now(timezone.utc)
    await db.commit()
    order = await _load_order(db, order.id, org_id)
    return _serialize_order(order)


@router.post("/purchase-orders/{order_id}/cancel", response_model=PurchaseOrderResponse)
async def cancel_purchase_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(ApproverUser),
):
    org_id = current_user.organization_id
    order = await _load_order(db, order_id, org_id)
    if procurement_service.received_quantity(order) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A purchase order with recorded receipts cannot be cancelled.",
        )
    order.status = "cancelled"
    order.closed_at = datetime.now(timezone.utc)
    await db.commit()
    order = await _load_order(db, order.id, org_id)
    return _serialize_order(order)

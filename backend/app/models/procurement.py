"""Procurement: requisition -> competitive bids -> purchase order -> receipt.

Closes the control gap between "we need something" and "we paid a vendor".
Spend is committed before an invoice arrives, competing quotes are recorded so
vendor selection can be defended in an audit, and goods/services are confirmed
received before the matching bill is allowed to post.

    PurchaseRequisition   what is needed, costed, and routed for approval
      +- RequisitionLine  the individual items being requested
      +- VendorQuote      competing bids captured against the requisition
    PurchaseOrder         the approved commitment issued to the winning vendor
      +- PurchaseOrderLine  ordered quantities, priced and coded to the GL
      +- PurchaseOrderReceipt / ReceiptLine  what actually arrived

A vendor bill may reference the purchase order it settles; the three-way match
in :mod:`app.services.procurement_service` then verifies order, receipt and
invoice agree before the bill posts to the ledger.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.approval import ApprovalMixin
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

REQUISITION_STATUSES = (
    "draft",
    "submitted",
    "approved",
    "rejected",
    "ordered",
    "cancelled",
)
PURCHASE_ORDER_STATUSES = (
    "issued",
    "partially_received",
    "received",
    "closed",
    "cancelled",
)
# Open states in which a purchase order can still be received against or billed.
PO_OPEN_STATUSES = ("issued", "partially_received", "received")


class PurchaseRequisition(ApprovalMixin, SoftDeleteMixin, TimestampMixin, Base):
    """A request to spend, routed for approval before any commitment is made."""

    __tablename__ = "purchase_requisitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    requisition_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the spend lands operationally; drives office-level budget reporting.
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    needed_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    estimated_total: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Set when a purchase order is raised, so a requisition cannot be ordered twice.
    ordered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lines: Mapped[list["RequisitionLine"]] = relationship(
        back_populates="requisition",
        cascade="all, delete-orphan",
        order_by="RequisitionLine.line_number",
    )
    quotes: Mapped[list["VendorQuote"]] = relationship(
        back_populates="requisition",
        cascade="all, delete-orphan",
        order_by="VendorQuote.amount",
    )
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="requisition"
    )


class RequisitionLine(TimestampMixin, Base):
    """A single requested item, costed and coded to a GL expense account."""

    __tablename__ = "requisition_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requisition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_requisitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("1"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True, index=True
    )

    requisition: Mapped["PurchaseRequisition"] = relationship(back_populates="lines")


class VendorQuote(TimestampMixin, Base):
    """A competing bid captured against a requisition."""

    __tablename__ = "vendor_quotes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requisition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_requisitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Required when the winning bid is not the cheapest, so the buyer has to
    # justify the choice on the record rather than in an email thread.
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requisition: Mapped["PurchaseRequisition"] = relationship(back_populates="quotes")
    vendor: Mapped["Vendor"] = relationship()


class PurchaseOrder(TimestampMixin, Base):
    """An approved commitment issued to the winning vendor."""

    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_requisitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    po_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(25), default="issued", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    # Percentage tolerance allowed when matching an invoice to this order.
    match_tolerance_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("5"), nullable=False
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requisition: Mapped["PurchaseRequisition | None"] = relationship(
        back_populates="purchase_orders"
    )
    vendor: Mapped["Vendor"] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_number",
    )
    receipts: Mapped[list["PurchaseOrderReceipt"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderReceipt.received_on",
    )


class PurchaseOrderLine(TimestampMixin, Base):
    """An ordered item, priced and coded, tracking how much has been received."""

    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("1"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    quantity_received: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True, index=True
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")


class PurchaseOrderReceipt(TimestampMixin, Base):
    """Confirmation that ordered goods or services actually arrived."""

    __tablename__ = "purchase_order_receipts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="receipts")
    lines: Mapped[list["ReceiptLine"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )


class ReceiptLine(TimestampMixin, Base):
    """Quantity received against a single purchase-order line."""

    __tablename__ = "purchase_order_receipt_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    receipt: Mapped["PurchaseOrderReceipt"] = relationship(back_populates="lines")
    purchase_order_line: Mapped["PurchaseOrderLine"] = relationship()


from app.models.vendor import Vendor  # noqa: E402

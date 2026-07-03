"""Accounts-receivable-lite models (Phase 1.1).

A lightweight accounts-receivable ledger that mirrors the accounts-payable
module (``vendor_bill``) but on the sell side. It lets finance staff bill
tenants/counterparties and record the cash received against those invoices,
posting both into the audit-grade general ledger:

  - ``Customer``            — an AR counterparty (tenant, licensee, other payer),
                              paralleling ``Vendor`` on the AP side.
  - ``CustomerInvoice``     — an invoice issued to a customer, allocated across
                              one or more GL revenue accounts and debited to
                              Accounts Receivable.
  - ``CustomerInvoiceLine`` — a single revenue-allocation line on an invoice.
  - ``CustomerReceipt``     — cash received against an invoice, debiting Cash and
                              crediting Accounts Receivable.

An invoice is captured as a ``draft`` (fully editable), then ``finalized`` to an
immutable record that posts ``Dr Accounts Receivable / Cr revenue`` to the GL.
Receipts may be recorded against a finalized invoice, each posting
``Dr Cash / Cr Accounts Receivable``. The invoice's running status (open /
partial / paid) is derived from the sum of its receipts.

Amounts are USD-only; multi-currency / FX handling is deferred. A ``currency``
column is carried defaulting to ``USD`` so the schema is forward-compatible.
"""

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

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

# Invoice workflow states.
INVOICE_STATUSES = {"draft", "finalized", "void"}
# Derived receipt states (computed from receipts, not stored on the row).
RECEIPT_STATES = {"open", "partial", "paid"}


class Customer(SoftDeleteMixin, TimestampMixin, Base):
    """An accounts-receivable counterparty billed via customer invoices."""

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoices: Mapped[list["CustomerInvoice"]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class CustomerInvoice(TimestampMixin, Base):
    """An invoice issued to a customer, receivable in the GL."""

    __tablename__ = "customer_invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Human-facing invoice number (free-form; may be auto-assigned by the caller).
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # USD-only for now; FX deferred.
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Snapshot of the invoice total (sum of lines) for quick listing/reporting.
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    # Optional provenance when generated from another source (e.g. a CAM true-up).
    source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Lifecycle ---
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalized_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # GL journal entry created when the invoice is finalized/posted.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )

    customer: Mapped["Customer"] = relationship(back_populates="invoices")
    lines: Mapped[list["CustomerInvoiceLine"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="CustomerInvoiceLine.line_number",
    )
    receipts: Mapped[list["CustomerReceipt"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="CustomerReceipt.receipt_date",
    )


class CustomerInvoiceLine(TimestampMixin, Base):
    """A single revenue-account allocation line on a customer invoice."""

    __tablename__ = "customer_invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Revenue (or other) GL account this line is credited to on posting.
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    invoice: Mapped["CustomerInvoice"] = relationship(back_populates="lines")
    account: Mapped["GLAccount"] = relationship()


class CustomerReceipt(TimestampMixin, Base):
    """Cash received against a customer invoice (Dr Cash / Cr Accounts Receivable)."""

    __tablename__ = "customer_receipts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # Free-form receipt method label (e.g. "check", "ach", "wire", "card").
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    invoice: Mapped["CustomerInvoice"] = relationship(back_populates="receipts")


from app.models.general_ledger import GLAccount  # noqa: E402

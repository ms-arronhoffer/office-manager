"""Accounts-payable-lite models (Phase 5).

A lightweight accounts-payable ledger that lets finance staff record vendor
bills and the payments made against them, posting both into the audit-grade
general ledger:

  - ``VendorBill``     — a bill/invoice received from a vendor, expensed across
                         one or more GL accounts and credited to Accounts Payable.
  - ``VendorBillLine`` — a single expense allocation line on a bill.
  - ``VendorPayment``  — a cash payment applied to a bill, debiting Accounts
                         Payable and crediting Cash.

A bill is captured as a ``draft`` (fully editable), then ``finalized`` to an
immutable record that posts ``Dr expense / Cr Accounts Payable`` to the GL.
Payments may be recorded against a finalized bill, each posting
``Dr Accounts Payable / Cr Cash``. The bill's running status (open / partial /
paid) is derived from the sum of its payments.

Amounts are USD-only; multi-currency / FX handling is deferred. A ``currency``
column is carried defaulting to ``USD`` so the schema is forward-compatible.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Bill workflow states.
BILL_STATUSES = {"draft", "finalized", "void"}
# Derived payment states (computed from payments, not stored on the row).
PAYMENT_STATES = {"open", "partial", "paid"}


class VendorBill(TimestampMixin, Base):
    """A vendor bill/invoice expensed to the GL and credited to Accounts Payable."""

    __tablename__ = "vendor_bills"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Vendor-supplied invoice/bill number (free-form).
    bill_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # USD-only for now; FX deferred.
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Snapshot of the bill total (sum of lines) for quick listing/reporting.
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    # --- Lifecycle ---
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalized_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # GL journal entry created when the bill is finalized/posted.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )

    vendor: Mapped["Vendor"] = relationship()
    lines: Mapped[list["VendorBillLine"]] = relationship(
        back_populates="bill",
        cascade="all, delete-orphan",
        order_by="VendorBillLine.line_number",
    )
    payments: Mapped[list["VendorPayment"]] = relationship(
        back_populates="bill",
        cascade="all, delete-orphan",
        order_by="VendorPayment.payment_date",
    )


class VendorBillLine(TimestampMixin, Base):
    """A single expense-account allocation line on a vendor bill."""

    __tablename__ = "vendor_bill_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Expense (or other) GL account this line is charged to.
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    bill: Mapped["VendorBill"] = relationship(back_populates="lines")
    account: Mapped["GLAccount"] = relationship()


class VendorPayment(TimestampMixin, Base):
    """A cash payment applied to a vendor bill (Dr Accounts Payable / Cr Cash)."""

    __tablename__ = "vendor_payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    bill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # Free-form payment method label (e.g. "check", "ach", "wire", "card").
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    bill: Mapped["VendorBill"] = relationship(back_populates="payments")


from app.models.vendor import Vendor  # noqa: E402
from app.models.general_ledger import GLAccount  # noqa: E402

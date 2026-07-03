"""Rent collection & payments-in models (Phase 2.3 — org-as-lessor).

Layers inbound-money mechanics on top of the Phase 2.1 resident/unit/lease
domain and reuses the Phase 1.1 accounts-receivable ledger for GL posting:

* :class:`RentCharge`     — a recurring charge schedule attached to a
  :class:`~app.models.resident.ResidentLease` (rent, parking, utility, etc.).
  Drives automatic invoice generation and late-fee automation. Billing state is
  tracked with ``last_billed_period`` for idempotent catch-up billing.
* :class:`SecurityDeposit` — a deposit held against a lease, with its own GL
  postings (``Dr Cash / Cr Security Deposits Held`` on receipt; the reverse on
  return, with any forfeited portion recognised as income).

Recurring rent invoices are ordinary :class:`~app.models.customer_invoice.CustomerInvoice`
rows tagged ``source="rent"`` so they flow through the same audit-grade ledger,
aging report, and receipt handling as the rest of accounts receivable. Amounts
are USD-only, matching the other accounting modules.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

# Kinds of recurring charge a schedule can bill.
RENT_CHARGE_TYPES = ("rent", "parking", "utility", "pet", "storage", "other")

# Billing cadence. Only monthly is auto-generated today; the column is carried so
# weekly/annual can be added without a schema change.
RENT_FREQUENCIES = ("monthly",)

# How a late fee is computed once a charge is past its grace period.
LATE_FEE_TYPES = ("none", "flat", "percent")

# Lifecycle of a security deposit.
DEPOSIT_STATUSES = ("held", "partially_returned", "returned", "forfeited")


class RentCharge(SoftDeleteMixin, TimestampMixin, Base):
    """A recurring charge schedule that bills a resident lease on a cadence."""

    __tablename__ = "rent_charges"
    __table_args__ = (
        Index("idx_rent_charges_lease", "resident_lease_id"),
        Index("idx_rent_charges_active", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    resident_lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resident_leases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charge_type: Mapped[str] = mapped_column(
        String(20), default="rent", nullable=False, server_default="rent"
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(
        String(20), default="monthly", nullable=False, server_default="monthly"
    )
    # Day of month the charge is due (1-28 recommended to stay valid every month).
    day_of_month: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1"
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Days after the due date before a late fee applies.
    grace_days: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    late_fee_type: Mapped[str] = mapped_column(
        String(10), default="none", nullable=False, server_default="none"
    )
    # Flat dollar amount or percent (of the outstanding balance), per late_fee_type.
    late_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Revenue GL account code the generated invoice line credits.
    revenue_account_code: Mapped[str] = mapped_column(
        String(20), default="4000", nullable=False, server_default="4000"
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # First day of the most recent period billed; drives idempotent catch-up.
    last_billed_period: Mapped[date | None] = mapped_column(Date, nullable=True)

    lease: Mapped["ResidentLease"] = relationship("ResidentLease")


class SecurityDeposit(SoftDeleteMixin, TimestampMixin, Base):
    """A security deposit held against a resident lease (a GL liability)."""

    __tablename__ = "security_deposits"
    __table_args__ = (
        Index("idx_security_deposits_lease", "resident_lease_id"),
        Index("idx_security_deposits_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    resident_lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resident_leases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    held_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="held", nullable=False, server_default="held"
    )
    returned_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False, server_default="0"
    )
    forfeited_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False, server_default="0"
    )
    returned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # GL entries: one for the receipt, one for the return/forfeiture.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    return_journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )

    lease: Mapped["ResidentLease"] = relationship("ResidentLease")


# Resolved at runtime by SQLAlchemy to avoid a circular import.
from app.models.resident import ResidentLease  # noqa: E402,F401

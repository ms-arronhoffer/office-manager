"""Persisted lease-lifecycle accounting events (Phase 4).

ASC 842 / IFRS 16 requires the lease liability and right-of-use (ROU) asset to be
*remeasured* when a lease changes after commencement. This module records those
post-commencement events:

  - ``modification``        — a change in consideration or term that is not a
                              separate contract (remeasure liability & ROU).
  - ``renewal``             — an extension / option exercise (a reassessment that
                              remeasures liability & ROU).
  - ``partial_termination`` — a decrease in scope; the liability and ROU are
                              reduced proportionately and a gain/loss recognised.
  - ``full_termination``    — the lease ends early; the remaining liability and
                              ROU are derecognised and a gain/loss recognised.

The pre-event carrying amounts, the revised terms, and the computed results are
all *snapshotted* onto the record so that a finalized event remains immutable and
audit-defensible even if the underlying lease is later edited. A finalized event
can be posted to the general ledger, linking the resulting journal entry back to
the event.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Supported lifecycle event types.
EVENT_TYPES = {"modification", "renewal", "partial_termination", "full_termination"}
# Event lifecycle.
EVENT_STATUSES = {"draft", "finalized"}


class LeaseLifecycleEvent(TimestampMixin, Base):
    """A single post-commencement remeasurement event for one lease."""

    __tablename__ = "lease_lifecycle_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    # --- Pre-event carrying amounts (snapshot at the effective date) ---
    pre_liability: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    pre_rou: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    # --- Revised terms (modification / renewal / remeasured partial term) ---
    new_payment_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    new_payment_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_annual_escalation_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6), nullable=True
    )
    new_incremental_borrowing_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6), nullable=True
    )
    remaining_term_months: Mapped[int | None] = mapped_column(nullable=True)
    new_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- Termination parameters ---
    # Fraction of the ROU asset / term retained after a partial termination (0..1).
    remaining_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True
    )
    # Cash penalty paid to terminate (full or partial termination).
    termination_penalty: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    # --- Computed results (snapshot) ---
    revised_liability: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    liability_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    rou_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    post_liability: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    post_rou: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    # Positive => gain (credit P&L); negative => loss (debit P&L).
    gain_loss: Mapped[Decimal] = mapped_column(
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
    # GL journal entry created when the event is posted.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    lease: Mapped["Lease"] = relationship()


from app.models.lease import Lease  # noqa: E402

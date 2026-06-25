"""Persisted CAM (common-area-maintenance) reconciliation models (Phase 3).

US-commercial operating-expense recovery reconciliation. A reconciliation
captures, for one lease and one year, the actual operating-expense pool and the
lease's recovery terms (pro-rata share, gross-up, base-year/expense-stop, and
controllable-expense caps), then computes the tenant's recoverable obligation
and the resulting true-up (tenant owes) or credit (tenant is owed).

The recovery terms and the computed results are snapshotted onto the record so
that a *finalized* statement remains immutable and audit-defensible even if the
underlying lease terms later change. A finalized reconciliation can be posted to
the general ledger, linking the resulting journal entry back to the statement.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Cap structures for controllable-expense increase limits.
CAP_TYPES = {"cumulative_compounded", "cumulative", "non_cumulative"}
# Reconciliation lifecycle.
RECON_STATUSES = {"draft", "finalized"}


class CamReconciliation(TimestampMixin, Base):
    """A CAM reconciliation statement for one lease and one year."""

    __tablename__ = "cam_reconciliations"
    __table_args__ = (
        UniqueConstraint("lease_id", "year", name="uq_cam_recon_lease_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Recovery terms (snapshot) ---
    # Tenant's pro-rata share of the building, as a fraction (0..1).
    pro_rata_share: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    rentable_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    building_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Gross-up occupancy standard (e.g. 0.95) and the year's actual occupancy.
    gross_up_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    occupancy_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    # Base-year stop expressed as a tenant-share dollar amount.
    base_year_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Expense stop expressed as dollars per rentable square foot.
    expense_stop_psf: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    # Annual cap on controllable-expense increases (fraction, e.g. 0.05).
    cap_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    cap_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cap_base_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Tenant-share controllable amount in the cap base year.
    cap_base_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Estimates billed to / collected from the tenant during the year.
    estimated_paid: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    # --- Computed results (snapshot) ---
    total_pool: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    controllable_pool: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    noncontrollable_pool: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    tenant_share_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    cap_applied: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    offset_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    recoverable_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    # Positive => tenant owes a true-up; negative => credit owed to tenant.
    balance_due: Mapped[Decimal] = mapped_column(
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
    # GL journal entry created when the reconciliation is posted.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    lease: Mapped["Lease"] = relationship()
    lines: Mapped[list["CamReconciliationLine"]] = relationship(
        back_populates="reconciliation",
        cascade="all, delete-orphan",
        order_by="CamReconciliationLine.line_number",
    )


class CamReconciliationLine(TimestampMixin, Base):
    """A single operating-expense category within a CAM reconciliation."""

    __tablename__ = "cam_reconciliation_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cam_reconciliations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # Controllable expenses are subject to the annual cap; non-controllable
    # (taxes, insurance, utilities, ...) pass through uncapped.
    controllable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Variable expenses eligible to be grossed up to the occupancy standard.
    gross_up_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    actual_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    # actual_amount after gross-up has been applied (snapshot).
    grossed_up_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )

    reconciliation: Mapped["CamReconciliation"] = relationship(back_populates="lines")


from app.models.lease import Lease  # noqa: E402

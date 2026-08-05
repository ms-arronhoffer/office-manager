"""Billable-unit metering snapshot.

A monthly, immutable record of how many billable units an organisation had, used
to drive per-unit (banded) billing and to show a customer what drove their bill.
The unit definition lives in :mod:`app.services.metering_service`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BillableUnitSnapshot(Base):
    """Count of an org's billable units for one billing period."""

    __tablename__ = "billable_unit_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "period_month", name="uq_billable_unit_snapshot_org_period"
        ),
        Index("idx_billable_unit_snapshots_org", "organization_id"),
        Index("idx_billable_unit_snapshots_period", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Billing period the snapshot describes, "YYYY-MM" (matches UsageEvent).
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    billable_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Per-category counts that sum to ``billable_units``.
    breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

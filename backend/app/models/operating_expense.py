import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OperatingExpense(TimestampMixin, Base):
    """CAM and operating expense record for a lease-year."""

    __tablename__ = "operating_expenses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # category: CAM, insurance, taxes, utilities, other
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    budgeted: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    actual: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lease: Mapped["Lease"] = relationship(back_populates="operating_expenses")


from app.models.lease import Lease  # noqa: E402

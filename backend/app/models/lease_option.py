import uuid
from datetime import datetime, timezone, date
from decimal import Decimal

from sqlalchemy import String, Text, DateTime, Date, ForeignKey, Numeric, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LeaseOption(Base):
    __tablename__ = "lease_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id", ondelete="CASCADE"), nullable=False)
    option_type: Mapped[str] = mapped_column(String(30), nullable=False)
    exercise_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    exercise_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_required_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_rent_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

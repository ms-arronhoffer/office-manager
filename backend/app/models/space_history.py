"""Space occupancy snapshot — records headcount/sqft state at a point in time."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SpaceHistory(TimestampMixin, Base):
    __tablename__ = "space_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    office_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_sqft: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    usable_sqft: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    headcount_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    space_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

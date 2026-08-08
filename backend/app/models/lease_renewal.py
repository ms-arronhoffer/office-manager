import uuid
from datetime import datetime, timezone, date
from decimal import Decimal

from sqlalchemy import String, Text, Boolean, DateTime, Date, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LeaseRenewal(Base):
    __tablename__ = "lease_renewals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="in_progress")
    target_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_rent_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terms_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The person accountable for driving this renewal to a decision. Without an
    # owner a deadline is only a dashboard number, not work someone is doing.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Latest date the notice can still be served without breaching the lease.
    notice_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Set when the record was opened automatically by the deadline scheduler
    # rather than by a person, so reporting can distinguish the two.
    auto_opened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # How the notice was delivered and the reference proving it (courier
    # tracking number, signed receipt, email message id).
    notice_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notice_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

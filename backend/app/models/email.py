import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, ARRAY, DateTime
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class EmailReminderRule(TimestampMixin, Base):
    __tablename__ = "email_reminder_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    days_before: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_emails: Mapped[list[str]] = mapped_column(PG_ARRAY(String(255)), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Stored as timezone-aware UTC; matches the rest of the app's timestamp convention.
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailLog(Base):
    __tablename__ = "email_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_reminder_rules.id"), nullable=True)
    sent_to: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Must be timezone-aware to match the Python default lambda (datetime.now(timezone.utc));
    # without DateTime(timezone=True), Postgres stores TIMESTAMP WITHOUT TIME ZONE and asyncpg
    # rejects aware datetimes ("can't subtract offset-naive and offset-aware datetimes").
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), default="sent", nullable=False)

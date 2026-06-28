import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, ARRAY, DateTime, Index
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


# Supported digest/delivery cadences for a reminder rule.
DELIVERY_MODES = ("immediate", "daily_digest", "weekly_digest")


class EmailReminderRule(TimestampMixin, Base):
    __tablename__ = "email_reminder_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    days_before: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_emails: Mapped[list[str]] = mapped_column(PG_ARRAY(String(255)), nullable=False)
    # Structured (role/user-linked) recipients, resolved to addresses at send time.
    # These supplement the free-text ``recipient_emails`` list.
    recipient_roles: Mapped[list[str] | None] = mapped_column(PG_ARRAY(String(20)), nullable=True)
    recipient_user_ids: Mapped[list[uuid.UUID] | None] = mapped_column(PG_ARRAY(PG_UUID(as_uuid=True)), nullable=True)
    # Delivery cadence: immediate (one email per event) or a batched digest.
    delivery_mode: Mapped[str] = mapped_column(String(20), default="immediate", nullable=False)
    # Escalation chain: day offsets *after* the initial notice at which the rule
    # re-fires while the underlying condition remains unacknowledged/unmet.
    escalation_offsets: Mapped[list[int] | None] = mapped_column(PG_ARRAY(Integer), nullable=True)
    # Extra recipients added at each escalation step (e.g. a manager/owner).
    escalation_recipient_emails: Mapped[list[str] | None] = mapped_column(PG_ARRAY(String(255)), nullable=True)
    # When true, notices include a tokenized acknowledge link and escalation
    # halts once a recipient acknowledges.
    require_acknowledgement: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Stored as timezone-aware UTC; matches the rest of the app's timestamp convention.
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailAcknowledgement(TimestampMixin, Base):
    """Tracks acknowledgement of a reminder for a specific (rule, entity) pair.

    A tokenized public link lets a recipient acknowledge a notice without
    logging in (mirroring the waiver/client-portal token pattern). While an
    acknowledgement is outstanding, the rule's escalation steps keep firing.
    """

    __tablename__ = "email_acknowledgements"
    __table_args__ = (
        Index("idx_email_ack_rule_entity", "rule_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_reminder_rules.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    ack_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Highest escalation step that has been emitted for this notice so far.
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


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
    # Which escalation step produced this email (0 = initial notice).
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

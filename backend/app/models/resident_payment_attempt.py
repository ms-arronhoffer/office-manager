"""Resident processor attempts and deduplicated tenant Stripe webhook events."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ResidentPaymentAttempt(TimestampMixin, Base):
    __tablename__ = "resident_payment_attempts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_resident_payment_attempt_org_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lease_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resident_leases.id", ondelete="SET NULL"), nullable=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_invoices.id", ondelete="SET NULL"), nullable=True
    )
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resident_payment_methods.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    method_type: Mapped[str] = mapped_column(String(12), nullable=False)
    processor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="processing", nullable=False, server_default="processing"
    )
    allocation_json: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    return_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customer_receipts.id", ondelete="SET NULL"), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResidentPaymentWebhookEvent(TimestampMixin, Base):
    __tablename__ = "resident_payment_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "stripe_event_id", name="uq_resident_payment_webhook_org_event"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stripe_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    processor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
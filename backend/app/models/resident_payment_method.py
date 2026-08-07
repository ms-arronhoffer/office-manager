"""Saved resident payment methods (Phase 2.3 — resident-initiated payments).

A resident stores a *tokenised* card or bank account with the payment processor
and this table keeps only the opaque processor token plus non-sensitive display
detail (brand + last four digits) so the portal can render "Visa ····4242"
without the application ever touching a PAN or full account number.

Autopay lives on :class:`~app.models.resident.ResidentLease` and points at one
of these rows, so a lease is charged against a method the resident explicitly
saved.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, _utcnow

# Processors this table can hold tokens for.
PAYMENT_METHOD_PROCESSORS = ("stripe",)


class ResidentPaymentMethod(Base):
    """An opaque, tokenised payment instrument saved by a resident."""

    __tablename__ = "resident_payment_methods"
    __table_args__ = (
        Index("idx_resident_payment_methods_org", "organization_id"),
        Index("idx_resident_payment_methods_resident", "resident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    resident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE"), nullable=False
    )
    processor: Mapped[str] = mapped_column(
        String(30), default="stripe", nullable=False, server_default="stripe"
    )
    # Opaque processor handle. Never a card/bank number.
    processor_token: Mapped[str] = mapped_column(String(255), nullable=False)
    method_type: Mapped[str] = mapped_column(
        String(12), default="card", nullable=False, server_default="card"
    )
    status: Mapped[str] = mapped_column(
        String(24), default="active", nullable=False, server_default="active"
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Display-only. Safe to render and log.
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    exp_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exp_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    consent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

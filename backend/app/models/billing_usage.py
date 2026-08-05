"""Durable monthly lease usage and tracked subscription discount codes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ActiveLeaseMonth(Base):
    """Proof that one lease was saved as Active during a billing month."""

    __tablename__ = "active_lease_months"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "lease_type",
            "lease_id",
            "period_month",
            name="uq_active_lease_month_org_lease_period",
        ),
        Index("idx_active_lease_month_org_period", "organization_id", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    lease_type: Mapped[str] = mapped_column(String(20), nullable=False)
    lease_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    first_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SubscriptionDiscountCode(TimestampMixin, Base):
    """A Stripe-backed code issued and tracked by Portfolio Desk."""

    __tablename__ = "subscription_discount_codes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_subscription_discount_codes_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    stripe_coupon_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    stripe_promotion_code_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    percent_off: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_off_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_in_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    times_redeemed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SubscriptionDiscountRedemption(Base):
    """An organization redemption observed on a completed Stripe Checkout."""

    __tablename__ = "subscription_discount_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "discount_code_id",
            "organization_id",
            "stripe_checkout_session_id",
            name="uq_subscription_discount_redemption_session",
        ),
        Index("idx_subscription_discount_redemption_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    discount_code_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscription_discount_codes.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

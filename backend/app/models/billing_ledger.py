"""Persisted billing ledger — the durable revenue source of truth (Phase 1).

Until now the platform only kept a coarse ``payment_status``/``plan`` snapshot on
:class:`~app.models.organization.Organization`, so MRR/ARR were *estimated* from
plan counts × hardcoded prices and there was no record of what was actually
billed, collected, refunded, or failed. This module introduces a lightweight
mirror of the Stripe billing objects so the super-admin engine can report real
revenue, reconcile against Stripe, and offer per-org billing history.

Tables (all amounts stored as integer **cents** in their stated ``currency``):

  - ``BillingSubscription`` — one row per Stripe subscription.
  - ``BillingInvoice``      — invoices issued to a customer.
  - ``BillingCharge``       — payments/charges (collected money).
  - ``BillingRefund``       — refunds against a charge.
  - ``BillingCredit``       — manual account credits / adjustments.
  - ``BillingCoupon``       — discount coupons mirrored from Stripe.

Every row carries a ``source`` tag (``stripe`` or ``manual``) so reconciliation
can distinguish synced Stripe data from admin-entered adjustments, mirroring the
GL source-tag convention used elsewhere (e.g. AP's ``ap`` source). Stripe object
IDs are unique to make webhook handling idempotent (upsert by stripe id).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Source tags distinguishing Stripe-synced rows from manual admin adjustments.
BILLING_SOURCES = {"stripe", "manual"}

SUBSCRIPTION_STATUSES = {
    "trialing", "active", "past_due", "canceled", "unpaid",
    "incomplete", "incomplete_expired", "paused",
}
INVOICE_STATUSES = {"draft", "open", "paid", "uncollectible", "void"}
CHARGE_STATUSES = {"succeeded", "pending", "failed"}
REFUND_STATUSES = {"succeeded", "pending", "failed", "canceled"}


class BillingSubscription(TimestampMixin, Base):
    """A mirror of a Stripe subscription, scoped to an organization."""

    __tablename__ = "billing_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(10), default="stripe", nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    # Recurring unit amount in cents (per-seat or flat) and quantity.
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    interval: Mapped[str] = mapped_column(String(10), default="month", nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coupon_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False, server_default="{}")


class BillingInvoice(TimestampMixin, Base):
    """A mirror of a Stripe invoice."""

    __tablename__ = "billing_invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(10), default="stripe", nullable=False)
    stripe_invoice_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_paid_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_due_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hosted_invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False, server_default="{}")


class BillingCharge(TimestampMixin, Base):
    """A mirror of a Stripe charge/payment (money collected, or failed)."""

    __tablename__ = "billing_charges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(10), default="stripe", nullable=False)
    stripe_charge_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="succeeded", nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_refunded_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    charged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False, server_default="{}")


class BillingRefund(TimestampMixin, Base):
    """A mirror of a Stripe refund against a charge."""

    __tablename__ = "billing_refunds"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(10), default="stripe", nullable=False)
    stripe_refund_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    stripe_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="succeeded", nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False, server_default="{}")


class BillingCredit(TimestampMixin, Base):
    """A manual account credit/adjustment applied to an org by an admin."""

    __tablename__ = "billing_credits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(10), default="manual", nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BillingCoupon(TimestampMixin, Base):
    """A mirror of a Stripe coupon / discount."""

    __tablename__ = "billing_coupons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(10), default="stripe", nullable=False)
    stripe_coupon_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    percent_off: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_off_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    duration: Mapped[str] = mapped_column(String(20), default="once", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False, server_default="{}")

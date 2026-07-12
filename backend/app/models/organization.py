import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Boolean, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(20), default="starter", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # Timestamp when the org most recently entered the 'past_due' state. Used to
    # enforce a grace period (see app.services.entitlements.PAST_DUE_GRACE_DAYS).
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-org entitlement overrides; keys are validated against the entitlements
    # catalog (app.services.entitlements). Override values win over plan defaults.
    entitlement_overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    # Primary categories (lines of business) the org runs, e.g. "commercial",
    # "residential", "self_storage". Managed by the org's own admins. Distinct
    # from plan entitlements: this expresses *what business the customer runs*,
    # while entitlements express *what the plan allows*. See
    # app.services.categories for the canonical set and resolution rules.
    enabled_categories: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False, server_default='["commercial", "residential"]'
    )
    # Platform (super-admin) category overrides. A mapping of category -> bool
    # that always wins over the org-managed ``enabled_categories`` above,
    # letting platform staff force a category on or off for an org.
    category_overrides: Mapped[dict[str, bool]] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )

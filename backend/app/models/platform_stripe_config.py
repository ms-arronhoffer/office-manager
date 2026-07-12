"""Platform-wide Stripe integration configuration.

A single-row table holding the Stripe credentials that back the SaaS billing
integration (super-admin console → Billing → Stripe Integration). Historically
these values came only from environment variables
(``settings.STRIPE_SECRET_KEY`` et al.), which meant they could not be
established or rotated without deploy access. This model lets a super-admin
manage them from the admin console instead.

Secret values (``secret_key``, ``webhook_secret``) are encrypted at rest via
:mod:`app.utils.crypto` and are never returned to the client — only a masked
hint is exposed. The non-secret publishable key and price ids are stored in
plaintext. Resolution precedence (DB over env) lives in
:mod:`app.services.stripe_settings`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PlatformStripeConfig(TimestampMixin, Base):
    """Singleton Stripe configuration for the whole platform."""

    __tablename__ = "platform_stripe_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Encrypted at rest — see app.utils.crypto.encrypt_secret/decrypt_secret.
    # Never returned to the client; only a masked hint is exposed.
    secret_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Non-secret values, safe to return verbatim.
    publishable_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_id_starter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_id_pro: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Enterprise is custom-priced per subscriber; there is no shared price id.
    # Enterprise subscriptions are identified by their Stripe Product, under which
    # each subscriber's bespoke price is created.
    product_id_enterprise: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verify_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_verify_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

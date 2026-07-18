"""Enterprise activation codes.

Enterprise is custom-priced per subscriber: sales negotiates a bespoke price and
provisions it as a Stripe Price under the single Enterprise Product
(``product_id_enterprise``). Rather than asking the customer to paste a raw
Stripe Price ID (guessable, typo-prone, and not really secret), a super-admin
mints an opaque *activation code* that maps to that price. The org admin enters
the code on the billing page to self-activate their negotiated Enterprise plan.

A code may optionally be bound to a specific organization and/or given an
expiry. Redemption is single-use but idempotent for the redeeming org: once an
org redeems a code, that same org may re-submit it (e.g. to retry an abandoned
checkout), but no other org can use it.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class EnterpriseActivationCode(TimestampMixin, Base):
    """An opaque code mapping to a bespoke Enterprise Stripe Price."""

    __tablename__ = "enterprise_activation_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Opaque code the customer enters. Unique so a code resolves to exactly one
    # bespoke price.
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # The Stripe Price ID (``price_...``) provisioned for this subscriber under
    # the platform's Enterprise Product.
    stripe_price_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional binding to a specific org. When set, only that org may redeem.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Single-use tracking (idempotent for the redeeming org).
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_by_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

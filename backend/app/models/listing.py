"""Vacancy listings & syndication marketing (Phase 2.5).

Turns a vacant :class:`~app.models.resident.RentalUnit` into an outward-facing
marketing *listing* and exposes those listings as **syndication feeds** that
external listing sites (Zillow, Apartments.com, etc.) can ingest.

Entities
--------
* :class:`VacancyListing` — a published (or draft) advertisement for a unit,
  carrying marketing copy, headline rent, availability, amenities and photos.
  A listing is a marketing surface layered on top of a unit; the unit remains
  the source of truth for occupancy and accounting.

Only USD rents are carried (a ``currency`` column exists for forward
compatibility), matching the rest of the property-management modules.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

# Lifecycle of a vacancy listing. ``published`` listings are the only ones that
# appear in syndication feeds; ``leased`` is a terminal state set when the unit
# is filled.
LISTING_STATUSES = ("draft", "published", "unpublished", "leased")


class VacancyListing(SoftDeleteMixin, TimestampMixin, Base):
    """A marketing listing advertising a vacant rental unit."""

    __tablename__ = "vacancy_listings"
    __table_args__ = (
        Index("idx_vacancy_listings_unit", "unit_id"),
        Index("idx_vacancy_listings_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rental_units.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Advertised rent — may differ from the unit's book ``market_rent``.
    marketing_rent: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    available_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Overrides for the unit's physical attributes when advertising.
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    square_feet: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Freeform marketing extras.
    amenities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    photos: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Where prospects apply / who to contact.
    application_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    unit: Mapped["RentalUnit"] = relationship("RentalUnit")


from app.models.resident import RentalUnit  # noqa: E402  (runtime relationship resolution)

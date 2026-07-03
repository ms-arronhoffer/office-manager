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
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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

    syndications: Mapped[list["ListingSyndication"]] = relationship(
        "ListingSyndication",
        back_populates="listing",
        cascade="all, delete-orphan",
    )


# Distribution portals a listing can be syndicated to. ``feed`` portals ingest
# the org's public syndication feed; ``webhook`` portals receive a JSON payload
# pushed to their ``endpoint_url`` when a listing is syndicated.
PORTAL_DELIVERY_MODES = ("feed", "webhook")

# Well-known listing portals offered out of the box. Staff can enable any of
# these (creating a :class:`ListingPortal`) or add fully custom portals.
KNOWN_PORTALS = (
    {
        "slug": "zillow",
        "name": "Zillow",
        "website_url": "https://www.zillow.com",
        "delivery_mode": "feed",
    },
    {
        "slug": "homes",
        "name": "Homes.com",
        "website_url": "https://www.homes.com",
        "delivery_mode": "feed",
    },
    {
        "slug": "apartments",
        "name": "Apartments.com",
        "website_url": "https://www.apartments.com",
        "delivery_mode": "feed",
    },
    {
        "slug": "realtor",
        "name": "Realtor.com",
        "website_url": "https://www.realtor.com",
        "delivery_mode": "feed",
    },
    {
        "slug": "trulia",
        "name": "Trulia",
        "website_url": "https://www.trulia.com",
        "delivery_mode": "feed",
    },
)


# Lifecycle of a per-listing, per-portal syndication record.
SYNDICATION_STATUSES = ("pending", "posted", "failed", "removed")


class ListingPortal(SoftDeleteMixin, TimestampMixin, Base):
    """An external listing portal a vacancy can be syndicated to.

    Covers the well-known networks (Zillow, Homes.com, Apartments.com, …) via
    their :data:`KNOWN_PORTALS` slug as well as fully custom portals a customer
    runs themselves.
    """

    __tablename__ = "listing_portals"
    __table_args__ = (
        Index("idx_listing_portals_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # ``zillow``/``homes``/``apartments``/… for known networks, or ``custom``.
    slug: Mapped[str] = mapped_column(String(50), nullable=False, default="custom")
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # For ``webhook`` delivery: the endpoint we POST listing payloads to.
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delivery_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="feed", server_default="feed"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # Freeform per-portal configuration (account id, feed options, …).
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    syndications: Mapped[list["ListingSyndication"]] = relationship(
        "ListingSyndication",
        back_populates="portal",
        cascade="all, delete-orphan",
    )


class ListingSyndication(TimestampMixin, Base):
    """Tracks that a listing has been posted to a particular portal."""

    __tablename__ = "listing_syndications"
    __table_args__ = (
        UniqueConstraint("listing_id", "portal_id", name="uq_listing_syndication"),
        Index("idx_listing_syndications_listing", "listing_id"),
        Index("idx_listing_syndications_portal", "portal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy_listings.id", ondelete="CASCADE"), nullable=False
    )
    portal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listing_portals.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Identifier the portal assigned to the posted listing, if any.
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    listing: Mapped["VacancyListing"] = relationship(
        "VacancyListing", back_populates="syndications"
    )
    portal: Mapped["ListingPortal"] = relationship(
        "ListingPortal", back_populates="syndications"
    )


from app.models.resident import RentalUnit  # noqa: E402  (runtime relationship resolution)

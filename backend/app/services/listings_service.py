"""Vacancy listing & syndication service (Phase 2.5).

Keeps the ``/api/v1/listings`` router thin: listing lifecycle (draft →
published → unpublished/leased) plus building the **syndication feeds** that
external listing sites consume. Two feed formats are produced from the same
published-listing set:

* a generic JSON feed (``build_json_feed``) for modern REST ingestion, and
* an XML feed (``build_xml_feed``) for the many listing networks that still
  accept a simple XML property feed.

Both feeds only ever expose ``published`` listings and derive missing physical
attributes (beds/baths/size/rent) from the underlying
:class:`~app.models.resident.RentalUnit`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.listing import (
    KNOWN_PORTALS,
    ListingPortal,
    ListingSyndication,
    VacancyListing,
)
from app.models.resident import RentalUnit


class ListingError(ValueError):
    """Raised for vacancy-listing rule violations."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_listing(
    db: AsyncSession, listing_id: uuid.UUID, org_id
) -> VacancyListing | None:
    return (
        await db.execute(
            select(VacancyListing)
            .where(
                VacancyListing.id == listing_id,
                VacancyListing.organization_id == org_id,
                VacancyListing.is_deleted.is_(False),
            )
            .options(selectinload(VacancyListing.unit))
        )
    ).scalar_one_or_none()


async def validate_unit(db: AsyncSession, unit_id: uuid.UUID, org_id) -> RentalUnit:
    unit = (
        await db.execute(
            select(RentalUnit).where(
                RentalUnit.id == unit_id,
                RentalUnit.organization_id == org_id,
                RentalUnit.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if unit is None:
        raise ListingError("Rental unit not found.")
    return unit


def set_status(listing: VacancyListing, target: str) -> None:
    """Transition a listing's publish state, stamping ``published_at``."""
    if target == "published" and listing.status != "published":
        listing.published_at = _now()
    listing.status = target


# ---------------------------------------------------------------------------
# Syndication feeds
# ---------------------------------------------------------------------------

async def _published_listings(db: AsyncSession, org_id) -> list[VacancyListing]:
    return list(
        (
            await db.execute(
                select(VacancyListing)
                .where(
                    VacancyListing.organization_id == org_id,
                    VacancyListing.status == "published",
                    VacancyListing.is_deleted.is_(False),
                )
                .options(selectinload(VacancyListing.unit))
                .order_by(VacancyListing.published_at.desc())
            )
        )
        .scalars()
        .all()
    )


def _rent(listing: VacancyListing) -> Decimal | None:
    if listing.marketing_rent is not None:
        return listing.marketing_rent
    return listing.unit.market_rent if listing.unit else None


def _attr(listing: VacancyListing, name: str):
    """Return the listing override for a physical attribute, else the unit's."""
    value = getattr(listing, name)
    if value is not None:
        return value
    return getattr(listing.unit, name) if listing.unit else None


def _listing_dict(listing: VacancyListing) -> dict:
    unit = listing.unit
    rent = _rent(listing)
    return {
        "id": str(listing.id),
        "title": listing.title,
        "headline": listing.headline,
        "description": listing.description,
        "rent": str(rent) if rent is not None else None,
        "currency": listing.currency,
        "available_date": (
            listing.available_date.isoformat() if listing.available_date else None
        ),
        "bedrooms": _attr(listing, "bedrooms"),
        "bathrooms": (
            str(_attr(listing, "bathrooms"))
            if _attr(listing, "bathrooms") is not None
            else None
        ),
        "square_feet": (
            str(_attr(listing, "square_feet"))
            if _attr(listing, "square_feet") is not None
            else None
        ),
        "unit_number": unit.unit_number if unit else None,
        "amenities": listing.amenities or [],
        "photos": listing.photos or [],
        "application_url": listing.application_url,
        "contact_email": listing.contact_email,
        "contact_phone": listing.contact_phone,
        "published_at": (
            listing.published_at.isoformat() if listing.published_at else None
        ),
    }


async def build_json_feed(db: AsyncSession, org_id) -> dict:
    """Build a generic JSON syndication feed of published listings."""
    listings = await _published_listings(db, org_id)
    return {
        "generated_at": _now().isoformat(),
        "count": len(listings),
        "listings": [_listing_dict(x) for x in listings],
    }


def _text(parent: ET.Element, tag: str, value) -> None:
    el = ET.SubElement(parent, tag)
    el.text = "" if value is None else str(value)


async def build_xml_feed(db: AsyncSession, org_id) -> bytes:
    """Build a simple XML property feed for syndication networks."""
    listings = await _published_listings(db, org_id)
    root = ET.Element("Listings")
    root.set("generated", _now().isoformat())
    for listing in listings:
        data = _listing_dict(listing)
        node = ET.SubElement(root, "Listing")
        node.set("id", data["id"])
        for tag in (
            "title",
            "headline",
            "description",
            "rent",
            "currency",
            "available_date",
            "bedrooms",
            "bathrooms",
            "square_feet",
            "unit_number",
            "application_url",
            "contact_email",
            "contact_phone",
        ):
            _text(node, _pascal(tag), data[tag])
        amenities = ET.SubElement(node, "Amenities")
        for amenity in data["amenities"]:
            _text(amenities, "Amenity", amenity)
        photos = ET.SubElement(node, "Photos")
        for photo in data["photos"]:
            url = photo.get("url") if isinstance(photo, dict) else photo
            _text(photos, "Photo", url)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_"))


# ---------------------------------------------------------------------------
# Portal syndication
# ---------------------------------------------------------------------------

def known_portal_catalog() -> list[dict]:
    """Return the built-in catalog of well-known listing portals."""
    return [dict(p) for p in KNOWN_PORTALS]


async def get_portal(
    db: AsyncSession, portal_id: uuid.UUID, org_id
) -> ListingPortal | None:
    return (
        await db.execute(
            select(ListingPortal).where(
                ListingPortal.id == portal_id,
                ListingPortal.organization_id == org_id,
                ListingPortal.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()


async def list_portals(db: AsyncSession, org_id) -> list[ListingPortal]:
    return list(
        (
            await db.execute(
                select(ListingPortal)
                .where(
                    ListingPortal.organization_id == org_id,
                    ListingPortal.is_deleted.is_(False),
                )
                .order_by(ListingPortal.name)
            )
        )
        .scalars()
        .all()
    )


async def deliver_to_portal(portal: ListingPortal, payload: dict) -> tuple[str, str | None, str | None]:
    """Deliver a listing payload to a portal.

    Returns ``(status, external_reference, message)``. ``feed`` portals ingest
    the org's public syndication feed, so no push is made — the listing is simply
    marked as included. ``webhook`` portals receive a best-effort HTTP POST of
    the payload to their ``endpoint_url``; a delivery failure is captured as a
    ``failed`` status rather than raising, so one bad portal never blocks others.
    """
    if portal.delivery_mode == "webhook" and portal.endpoint_url:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.post(portal.endpoint_url, json=payload)
            if resp.status_code >= 400:
                return "failed", None, f"Portal returned HTTP {resp.status_code}"
            ref = None
            try:
                body = resp.json()
                if isinstance(body, dict):
                    ref = body.get("id") or body.get("reference")
            except ValueError:
                ref = None
            return "posted", (str(ref) if ref is not None else None), None
        except Exception as exc:  # noqa: BLE001 - never let one portal break syndication
            return "failed", None, f"Delivery failed: {exc}"
    # Feed-based portals pull from the org syndication feed.
    return "posted", None, "Included in syndication feed"


async def syndicate_listing(
    db: AsyncSession,
    listing: VacancyListing,
    portals: list[ListingPortal],
) -> list[ListingSyndication]:
    """Post a listing to each portal, creating/refreshing syndication records."""
    payload = _listing_dict(listing)
    existing = {
        s.portal_id: s
        for s in (
            await db.execute(
                select(ListingSyndication).where(
                    ListingSyndication.listing_id == listing.id
                )
            )
        )
        .scalars()
        .all()
    }
    results: list[ListingSyndication] = []
    for portal in portals:
        status_, ref, message = await deliver_to_portal(portal, payload)
        record = existing.get(portal.id)
        if record is None:
            record = ListingSyndication(
                organization_id=listing.organization_id,
                listing_id=listing.id,
                portal_id=portal.id,
            )
            db.add(record)
        record.status = status_
        record.external_reference = ref
        record.message = message
        record.payload = payload
        record.last_synced_at = _now()
        results.append(record)
    return results


async def list_syndications(
    db: AsyncSession, listing_id: uuid.UUID
) -> list[ListingSyndication]:
    return list(
        (
            await db.execute(
                select(ListingSyndication)
                .where(ListingSyndication.listing_id == listing_id)
                .options(selectinload(ListingSyndication.portal))
                .order_by(ListingSyndication.created_at)
            )
        )
        .scalars()
        .all()
    )

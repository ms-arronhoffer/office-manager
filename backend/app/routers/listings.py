"""Vacancy listings & syndication API router (Phase 2.5) — ``/api/v1/listings``.

Advertises vacant units and syndicates them to external listing sites:

  - staff CRUD + publish/unpublish for :class:`VacancyListing` records
    (org-guarded, gated to ``admin``/``editor``; deletes to ``admin``)
  - public syndication feeds (``public_router``) that external listing networks
    poll — a generic JSON feed and an XML property feed, both scoped to one
    organisation and exposing only published listings.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.listing import LISTING_STATUSES, VacancyListing
from app.models.user import User
from app.services import listings_service as svc
from app.services.listings_service import ListingError

router = APIRouter()
public_router = APIRouter()

Editor = require_role("admin", "editor")
Admin = require_role("admin")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ListingCreate(BaseModel):
    unit_id: uuid.UUID
    title: str
    headline: str | None = None
    description: str | None = None
    marketing_rent: Decimal | None = None
    available_date: date | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    square_feet: Decimal | None = None
    amenities: list[str] | None = None
    photos: list[dict] | None = None
    application_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class ListingUpdate(BaseModel):
    title: str | None = None
    headline: str | None = None
    description: str | None = None
    marketing_rent: Decimal | None = None
    available_date: date | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    square_feet: Decimal | None = None
    amenities: list[str] | None = None
    photos: list[dict] | None = None
    application_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class ListingResponse(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    title: str
    headline: str | None
    description: str | None
    marketing_rent: Decimal | None
    currency: str
    available_date: date | None
    bedrooms: int | None
    bathrooms: Decimal | None
    square_feet: Decimal | None
    amenities: list | None
    photos: list | None
    application_url: str | None
    contact_email: str | None
    contact_phone: str | None
    status: str
    published_at: datetime | None

    class Config:
        from_attributes = True


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get(db: AsyncSession, listing_id: uuid.UUID, org_id) -> VacancyListing:
    listing = await svc.get_listing(db, listing_id, org_id)
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found.")
    return listing


# ─── Staff CRUD ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[ListingResponse])
async def list_listings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    unit_id: uuid.UUID | None = Query(None),
):
    stmt = select(VacancyListing).where(
        VacancyListing.organization_id == current_user.organization_id,
        VacancyListing.is_deleted.is_(False),
    )
    if status_filter is not None:
        stmt = stmt.where(VacancyListing.status == status_filter)
    if unit_id is not None:
        stmt = stmt.where(VacancyListing.unit_id == unit_id)
    listings = (
        await db.execute(stmt.order_by(VacancyListing.created_at.desc()))
    ).scalars().all()
    return listings


@router.post("", response_model=ListingResponse, status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: ListingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    try:
        await svc.validate_unit(db, payload.unit_id, current_user.organization_id)
    except ListingError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    listing = VacancyListing(
        organization_id=current_user.organization_id,
        status="draft",
        **payload.model_dump(),
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return listing


@router.get("/{listing_id}", response_model=ListingResponse)
async def get_listing(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get(db, listing_id, current_user.organization_id)


@router.patch("/{listing_id}", response_model=ListingResponse)
async def update_listing(
    listing_id: uuid.UUID,
    payload: ListingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    listing = await _get(db, listing_id, current_user.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(listing, field, value)
    await db.commit()
    await db.refresh(listing)
    return listing


@router.post("/{listing_id}/publish", response_model=ListingResponse)
async def publish_listing(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    listing = await _get(db, listing_id, current_user.organization_id)
    if listing.status == "leased":
        raise HTTPException(status.HTTP_409_CONFLICT, "A leased listing cannot be published.")
    svc.set_status(listing, "published")
    await db.commit()
    await db.refresh(listing)
    return listing


@router.post("/{listing_id}/unpublish", response_model=ListingResponse)
async def unpublish_listing(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    listing = await _get(db, listing_id, current_user.organization_id)
    svc.set_status(listing, "unpublished")
    await db.commit()
    await db.refresh(listing)
    return listing


@router.post("/{listing_id}/mark-leased", response_model=ListingResponse)
async def mark_leased(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    listing = await _get(db, listing_id, current_user.organization_id)
    svc.set_status(listing, "leased")
    await db.commit()
    await db.refresh(listing)
    return listing


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    listing = await _get(db, listing_id, current_user.organization_id)
    listing.is_deleted = True
    listing.deleted_at = datetime.utcnow()
    await db.commit()


# ─── Public syndication feeds ─────────────────────────────────────────────────

@public_router.get("/feed/{organization_id}.xml")
async def syndication_feed_xml(
    organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    xml = await svc.build_xml_feed(db, organization_id)
    return Response(content=xml, media_type="application/xml")


@public_router.get("/feed/{organization_id}")
async def syndication_feed_json(
    organization_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await svc.build_json_feed(db, organization_id)

"""Announcements API router (Phase 2.2) — ``/api/v1/announcements``.

Staff-facing mass communications to residents. An announcement is composed as a
``draft``, then sent, which fans it out over the selected channels (in-portal,
email, SMS) and records a per-resident delivery log. Residents see their
portal-channel announcements through the resident portal.

Reads are open to any authenticated org user; compose/send require
``admin``/``editor``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.announcement import (
    ANNOUNCEMENT_CHANNELS,
    Announcement,
)
from app.models.resident import RESIDENT_STATUSES
from app.models.user import User
from app.services import comms_service as svc
from app.services.comms_service import CommsError

router = APIRouter()

Editor = require_role("admin", "editor")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class AnnouncementCreate(BaseModel):
    title: str
    body: str
    channels: list[str] = ["portal"]
    audience_office_id: uuid.UUID | None = None
    audience_resident_status: str | None = None

    @field_validator("channels")
    @classmethod
    def _valid_channels(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if c not in ANNOUNCEMENT_CHANNELS]
        if bad:
            raise ValueError(
                f"Invalid channel(s): {', '.join(bad)}. "
                f"Allowed: {', '.join(ANNOUNCEMENT_CHANNELS)}."
            )
        if not v:
            raise ValueError("At least one channel is required.")
        return v

    @field_validator("audience_resident_status")
    @classmethod
    def _valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in RESIDENT_STATUSES:
            raise ValueError(
                f"Invalid resident status '{v}'. Allowed: {', '.join(RESIDENT_STATUSES)}."
            )
        return v


class AnnouncementUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    channels: list[str] | None = None
    audience_office_id: uuid.UUID | None = None
    audience_resident_status: str | None = None

    @field_validator("channels")
    @classmethod
    def _valid_channels(cls, v):
        if v is None:
            return v
        bad = [c for c in v if c not in ANNOUNCEMENT_CHANNELS]
        if bad:
            raise ValueError(f"Invalid channel(s): {', '.join(bad)}.")
        if not v:
            raise ValueError("At least one channel is required.")
        return v


class AnnouncementResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    title: str
    body: str
    channels: list[str]
    status: str
    audience_office_id: uuid.UUID | None
    audience_resident_status: str | None
    sent_at: datetime | None
    recipient_count: int
    created_at: datetime
    updated_at: datetime


class SendResult(BaseModel):
    recipients: int
    emailed: int
    texted: int
    channels: list[str]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize(a: Announcement, recipient_count: int | None = None) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=a.id,
        organization_id=a.organization_id,
        title=a.title,
        body=a.body,
        channels=a.channel_list(),
        status=a.status,
        audience_office_id=a.audience_office_id,
        audience_resident_status=a.audience_resident_status,
        sent_at=a.sent_at,
        recipient_count=(
            recipient_count
            if recipient_count is not None
            else len(a.recipients)
        ),
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


async def _load(db: AsyncSession, announcement_id: uuid.UUID, org_id) -> Announcement:
    a = (
        await db.execute(
            select(Announcement)
            .where(
                Announcement.id == announcement_id,
                Announcement.organization_id == org_id,
            )
            .options(selectinload(Announcement.recipients))
        )
    ).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    return a


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AnnouncementResponse])
async def list_announcements(
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Announcement)
        .where(Announcement.organization_id == current_user.organization_id)
        .options(selectinload(Announcement.recipients))
        .order_by(Announcement.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(Announcement.status == status_filter)
    result = await db.execute(stmt)
    return [_serialize(a) for a in result.scalars().unique().all()]


@router.post("", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    payload: AnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    a = Announcement(
        organization_id=current_user.organization_id,
        title=payload.title,
        body=payload.body,
        channels=",".join(payload.channels),
        audience_office_id=payload.audience_office_id,
        audience_resident_status=payload.audience_resident_status,
        status="draft",
    )
    db.add(a)
    await db.commit()
    return _serialize(a, recipient_count=0)


@router.get("/{announcement_id}", response_model=AnnouncementResponse)
async def get_announcement(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    a = await _load(db, announcement_id, current_user.organization_id)
    return _serialize(a)


@router.patch("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: uuid.UUID,
    payload: AnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    a = await _load(db, announcement_id, current_user.organization_id)
    if a.status == "sent":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sent announcement can no longer be edited.",
        )
    data = payload.model_dump(exclude_unset=True)
    if "channels" in data and data["channels"] is not None:
        a.channels = ",".join(data.pop("channels"))
    if payload.audience_resident_status is not None and payload.audience_resident_status not in RESIDENT_STATUSES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid resident status.")
    for field, value in data.items():
        setattr(a, field, value)
    await db.commit()
    await db.refresh(a)
    return _serialize(a)


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    a = await _load(db, announcement_id, current_user.organization_id)
    await db.delete(a)
    await db.commit()


@router.post("/{announcement_id}/send", response_model=SendResult)
async def send_announcement(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    a = await _load(db, announcement_id, current_user.organization_id)
    try:
        result = await svc.send_announcement(db, a, sent_by_id=current_user.id)
    except CommsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await db.commit()
    return SendResult(**result)

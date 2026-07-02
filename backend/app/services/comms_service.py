"""Resident communications service (Phase 2.2).

Resolves an :class:`Announcement`'s audience and fans it out over the requested
channels (in-portal record, email, SMS), recording a per-resident delivery row.
Sending is best-effort: a resident with no email/phone, or an unconfigured
transport, simply is not delivered on that channel — mirroring how the rest of
the app treats email when SMTP is unset.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.announcement import Announcement, AnnouncementRecipient
from app.models.resident import (
    ACTIVE_LEASE_STATUSES,
    RentalUnit,
    Resident,
    ResidentLease,
    ResidentLeaseOccupant,
)
from app.utils import email_client
from app.utils.sms_client import send_sms


class CommsError(ValueError):
    """Raised for communication/announcement rule violations."""


async def resolve_audience(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    office_id: uuid.UUID | None = None,
    resident_status: str | None = None,
) -> list[Resident]:
    """Return the residents an announcement targets.

    Filters non-deleted residents in the org by optional ``resident_status`` and,
    when ``office_id`` is given, by whether the resident has an active/pending
    lease on a unit in that property.
    """
    stmt = select(Resident).where(
        Resident.organization_id == organization_id,
        Resident.is_deleted.is_(False),
    )
    if resident_status:
        stmt = stmt.where(Resident.status == resident_status)

    if office_id is not None:
        # Residents linked to an active/pending lease on a unit in the property.
        stmt = stmt.where(
            Resident.id.in_(
                select(ResidentLeaseOccupant.resident_id)
                .join(ResidentLease, ResidentLease.id == ResidentLeaseOccupant.lease_id)
                .join(RentalUnit, RentalUnit.id == ResidentLease.unit_id)
                .where(
                    RentalUnit.office_id == office_id,
                    ResidentLease.is_deleted.is_(False),
                    ResidentLease.status.in_(ACTIVE_LEASE_STATUSES),
                )
            )
        )
    stmt = stmt.order_by(Resident.last_name, Resident.first_name)
    return list((await db.execute(stmt)).scalars().unique().all())


async def send_announcement(
    db: AsyncSession,
    announcement: Announcement,
    *,
    sent_by_id: uuid.UUID | None = None,
) -> dict:
    """Fan an announcement out to its audience and record deliveries.

    Idempotency: an already-``sent`` announcement is not re-sent. Returns a
    summary with per-channel delivery counts.
    """
    if announcement.status == "sent":
        raise CommsError("This announcement has already been sent.")

    channels = set(announcement.channel_list())
    residents = await resolve_audience(
        db,
        announcement.organization_id,
        office_id=announcement.audience_office_id,
        resident_status=announcement.audience_resident_status,
    )

    emailed = texted = 0
    for resident in residents:
        recipient = AnnouncementRecipient(
            announcement_id=announcement.id,
            resident_id=resident.id,
        )
        if "email" in channels and resident.email:
            if await email_client.send_email(
                resident.email, announcement.title, _html_body(announcement)
            ):
                recipient.emailed = True
                emailed += 1
        if "sms" in channels and resident.phone:
            if await send_sms(resident.phone, _sms_body(announcement)):
                recipient.texted = True
                texted += 1
        db.add(recipient)

    announcement.status = "sent"
    announcement.sent_at = datetime.now(timezone.utc)
    announcement.sent_by_id = sent_by_id

    return {
        "recipients": len(residents),
        "emailed": emailed,
        "texted": texted,
        "channels": sorted(channels),
    }


def _html_body(announcement: Announcement) -> str:
    safe = (announcement.body or "").replace("\n", "<br>")
    return f"<h2>{announcement.title}</h2><p>{safe}</p>"


def _sms_body(announcement: Announcement) -> str:
    text = f"{announcement.title}\n\n{announcement.body or ''}".strip()
    # Keep SMS within a single-ish segment where practical.
    return text[:480]

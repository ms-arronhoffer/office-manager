"""Resident portal — token-gated endpoints for external resident access (Phase 2.2).

Extends the existing portal-token pattern (client & vendor portals) to residents.
A staff member mints a single-use invite; the resident redeems it for a
persistent ``X-Resident-Token`` credential used to:

  * view their profile, leases (unit + rent/deposit terms), and documents,
  * submit maintenance requests that feed the existing ticketing system,
  * view a simple balance summary (rent/deposit; live payment history arrives
    with Phase 2.3), and
  * read announcements addressed to them.

Portal accounts reuse :class:`ClientPortalAccount` with ``entity_type="resident"``.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.announcement import Announcement, AnnouncementRecipient
from app.models.attachment import Attachment
from app.models.client_portal_account import ClientPortalAccount
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.resident import (
    RentalUnit,
    Resident,
    ResidentLease,
    ResidentLeaseOccupant,
)
from app.models.user import User
from app.schemas.attachment import AttachmentResponse

router = APIRouter()

_RESIDENT_ENTITY_TYPE = "resident"
_TOKEN_TTL_DAYS = 90
_SIGNUP_TTL_DAYS = 14
_RESIDENT_REQUEST_CATEGORY = "Resident Request"


# ─── Schemas ──────────────────────────────────────────────────────────────────

class InviteResponse(BaseModel):
    signup_token: str
    signup_url: str
    expires_at: datetime


class SignupRequest(BaseModel):
    token: str


class PortalSession(BaseModel):
    portal_token: str
    portal_url: str
    expires_at: datetime


class ResidentProfile(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    status: str

    model_config = {"from_attributes": True}


class PortalLease(BaseModel):
    id: uuid.UUID
    name: str | None
    status: str
    start_date: date | None
    end_date: date | None
    move_in_date: date | None
    rent_amount: Decimal | None
    rent_frequency: str
    security_deposit: Decimal | None
    currency: str
    unit_number: str | None
    unit_name: str | None


class BalanceSummary(BaseModel):
    currency: str
    monthly_rent: Decimal
    security_deposit: Decimal
    # Live receivables/payment history land in Phase 2.3; exposed as zero for now.
    balance_due: Decimal


class MaintenanceRequestCreate(BaseModel):
    subject: str
    description: str
    priority: str = "medium"


class PortalTicket(BaseModel):
    id: uuid.UUID
    subject: str
    description: str
    status: str
    priority: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalAnnouncement(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    sent_at: datetime | None
    read_at: datetime | None


# ─── Token helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_resident_account(
    x_resident_token: str = Header(None, alias="X-Resident-Token"),
    db: AsyncSession = Depends(get_db),
) -> ClientPortalAccount:
    if not x_resident_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing resident portal token")
    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.portal_token == x_resident_token,
                ClientPortalAccount.entity_type == _RESIDENT_ENTITY_TYPE,
            )
        )
    ).scalar_one_or_none()
    if account is None or account.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid resident portal token")
    expires = _aware(account.portal_token_expires_at)
    if expires is not None and expires < _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Resident portal token expired")
    account.last_active_at = _now()
    return account


async def _resident_for(db: AsyncSession, account: ClientPortalAccount) -> Resident:
    resident = (
        await db.execute(
            select(Resident).where(
                Resident.id == account.entity_id,
                Resident.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if resident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    return resident


# ─── Staff: invite ────────────────────────────────────────────────────────────

@router.post("/resident-portal/invite", response_model=InviteResponse)
async def invite_resident(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Mint (or refresh) a single-use portal invite for a resident."""
    resident_id = payload.get("resident_id")
    if not resident_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="resident_id is required")
    resident = (
        await db.execute(
            select(Resident).where(
                Resident.id == uuid.UUID(str(resident_id)),
                Resident.organization_id == current_user.organization_id,
                Resident.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if resident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")

    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.entity_type == _RESIDENT_ENTITY_TYPE,
                ClientPortalAccount.entity_id == resident.id,
                ClientPortalAccount.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()

    signup_token = secrets.token_hex(32)
    expires = _now() + timedelta(days=_SIGNUP_TTL_DAYS)
    if account is None:
        account = ClientPortalAccount(
            organization_id=current_user.organization_id,
            entity_type=_RESIDENT_ENTITY_TYPE,
            entity_id=resident.id,
        )
        db.add(account)
    account.signup_token = signup_token
    account.signup_token_expires_at = expires
    account.revoked_at = None
    await db.commit()
    return InviteResponse(
        signup_token=signup_token,
        signup_url=f"/resident-portal/signup?token={signup_token}",
        expires_at=expires,
    )


# ─── Public: signup ───────────────────────────────────────────────────────────

@router.post("/resident-portal/signup", response_model=PortalSession)
async def resident_signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
):
    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.signup_token == payload.token,
                ClientPortalAccount.entity_type == _RESIDENT_ENTITY_TYPE,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid signup token")
    expires = _aware(account.signup_token_expires_at)
    if expires is not None and expires < _now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signup token expired")

    portal_token = secrets.token_hex(32)
    portal_expires = _now() + timedelta(days=_TOKEN_TTL_DAYS)
    account.portal_token = portal_token
    account.portal_token_expires_at = portal_expires
    account.signup_token = None
    account.signup_token_expires_at = None
    account.activated_at = _now()
    await db.commit()
    return PortalSession(
        portal_token=portal_token,
        portal_url=f"/resident-portal?token={portal_token}",
        expires_at=portal_expires,
    )


# ─── Resident: profile / leases / balance ─────────────────────────────────────

@router.get("/resident-portal/me", response_model=ResidentProfile)
async def portal_me(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    resident = await _resident_for(db, account)
    await db.commit()
    return ResidentProfile.model_validate(resident)


async def _load_resident_leases(
    db: AsyncSession, resident_id: uuid.UUID
) -> list[ResidentLease]:
    return list(
        (
            await db.execute(
                select(ResidentLease)
                .join(
                    ResidentLeaseOccupant,
                    ResidentLeaseOccupant.lease_id == ResidentLease.id,
                )
                .where(
                    ResidentLeaseOccupant.resident_id == resident_id,
                    ResidentLease.is_deleted.is_(False),
                )
                .options(selectinload(ResidentLease.unit))
                .order_by(ResidentLease.created_at.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )


@router.get("/resident-portal/leases", response_model=list[PortalLease])
async def portal_leases(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    leases = await _load_resident_leases(db, account.entity_id)
    await db.commit()
    return [
        PortalLease(
            id=l.id,
            name=l.name,
            status=l.status,
            start_date=l.start_date,
            end_date=l.end_date,
            move_in_date=l.move_in_date,
            rent_amount=l.rent_amount,
            rent_frequency=l.rent_frequency,
            security_deposit=l.security_deposit,
            currency=l.currency,
            unit_number=l.unit.unit_number if l.unit else None,
            unit_name=l.unit.name if l.unit else None,
        )
        for l in leases
    ]


@router.get("/resident-portal/balance", response_model=BalanceSummary)
async def portal_balance(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    """Simple balance summary from the resident's active lease terms.

    Live receivables/payment history are introduced in Phase 2.3; until then the
    outstanding balance is reported as zero.
    """
    leases = await _load_resident_leases(db, account.entity_id)
    await db.commit()
    active = next(
        (l for l in leases if l.status in ("pending", "active")),
        leases[0] if leases else None,
    )
    rent = active.rent_amount if active and active.rent_amount else Decimal("0.00")
    deposit = active.security_deposit if active and active.security_deposit else Decimal("0.00")
    currency = active.currency if active else "USD"
    return BalanceSummary(
        currency=currency,
        monthly_rent=rent,
        security_deposit=deposit,
        balance_due=Decimal("0.00"),
    )


# ─── Resident: maintenance requests ───────────────────────────────────────────

async def _get_or_create_request_category(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> TicketCategory:
    existing = (
        await db.execute(
            select(TicketCategory).where(
                TicketCategory.organization_id == organization_id,
                TicketCategory.name == _RESIDENT_REQUEST_CATEGORY,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    category = TicketCategory(
        organization_id=organization_id, name=_RESIDENT_REQUEST_CATEGORY
    )
    db.add(category)
    await db.flush()
    return category


@router.post(
    "/resident-portal/maintenance-requests",
    response_model=PortalTicket,
    status_code=status.HTTP_201_CREATED,
)
async def submit_maintenance_request(
    payload: MaintenanceRequestCreate,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    from app.services.pm_service import _pick_creator_id

    resident = await _resident_for(db, account)
    if payload.priority not in ("low", "medium", "high"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid priority")

    leases = await _load_resident_leases(db, resident.id)
    office_id = next(
        (l.unit.office_id for l in leases if l.unit and l.unit.office_id is not None),
        None,
    )
    if office_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No property is associated with your lease; please contact management.",
        )

    creator_id = await _pick_creator_id(db, account.organization_id)
    if creator_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maintenance requests are temporarily unavailable; please contact management.",
        )
    category = await _get_or_create_request_category(db, account.organization_id)

    ticket = MaintenanceTicket(
        organization_id=account.organization_id,
        subject=payload.subject[:255],
        description=payload.description,
        priority=payload.priority,
        status="open",
        category_id=category.id,
        office_id=office_id,
        created_by_id=creator_id,
        submitted_by_resident_id=resident.id,
    )
    db.add(ticket)
    account.last_active_at = _now()
    await db.commit()
    await db.refresh(ticket)
    return PortalTicket.model_validate(ticket)


@router.get("/resident-portal/maintenance-requests", response_model=list[PortalTicket])
async def list_maintenance_requests(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    tickets = (
        await db.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.submitted_by_resident_id == account.entity_id,
                MaintenanceTicket.is_deleted.is_(False),
            )
            .order_by(MaintenanceTicket.created_at.desc())
        )
    ).scalars().all()
    await db.commit()
    return [PortalTicket.model_validate(t) for t in tickets]


# ─── Resident: documents ──────────────────────────────────────────────────────

@router.get("/resident-portal/documents", response_model=list[AttachmentResponse])
async def list_documents(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    attachments = (
        await db.execute(
            select(Attachment)
            .where(
                Attachment.entity_type == _RESIDENT_ENTITY_TYPE,
                Attachment.entity_id == account.entity_id,
            )
            .order_by(Attachment.created_at.desc())
        )
    ).scalars().all()
    await db.commit()
    return [AttachmentResponse.model_validate(a) for a in attachments]


# ─── Resident: announcements ──────────────────────────────────────────────────

@router.get("/resident-portal/announcements", response_model=list[PortalAnnouncement])
async def list_announcements(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Announcement, AnnouncementRecipient.read_at)
            .join(
                AnnouncementRecipient,
                AnnouncementRecipient.announcement_id == Announcement.id,
            )
            .where(AnnouncementRecipient.resident_id == account.entity_id)
            .order_by(Announcement.sent_at.desc())
        )
    ).all()
    await db.commit()
    return [
        PortalAnnouncement(
            id=a.id,
            title=a.title,
            body=a.body,
            sent_at=a.sent_at,
            read_at=read_at,
        )
        for a, read_at in rows
    ]

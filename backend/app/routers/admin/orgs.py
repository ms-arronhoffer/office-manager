"""Super-admin: organization management + impersonation."""
import io
import math
import uuid
from datetime import datetime, timedelta, timezone

import csv
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from jose import jwt
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.config import settings
from app.database import get_db
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.organization import Organization
from app.models.user import User
from app.services.activity_service import log_activity

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class OrgListItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    payment_status: str
    max_seats: int | None
    seat_count: int
    ticket_count: int
    trial_ends_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgDetail(OrgListItem):
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    onboarding_complete: bool
    open_ticket_count: int
    admin_notes: str | None


class OrgPatch(BaseModel):
    plan: str | None = None
    is_active: bool | None = None
    max_seats: int | None = None
    payment_status: str | None = None
    trial_ends_at: datetime | None = None
    onboarding_complete: bool | None = None
    admin_notes: str | None = None


class ImpersonateResponse(BaseModel):
    token: str
    impersonated_user_id: str
    impersonated_user_email: str


class PaginatedOrgs(BaseModel):
    items: list[OrgListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _org_stats(
    db: AsyncSession, org_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """Return seat_count, ticket_count, open_ticket_count for each org in one pass."""
    if not org_ids:
        return {}

    seat_rows = await db.execute(
        select(User.organization_id, func.count(User.id).label("cnt"))
        .where(User.organization_id.in_(org_ids), User.is_active.is_(True))
        .group_by(User.organization_id)
    )
    seats = {r[0]: r[1] for r in seat_rows.all()}

    ticket_rows = await db.execute(
        select(
            MaintenanceTicket.organization_id,
            func.count(MaintenanceTicket.id).label("total"),
            func.count(MaintenanceTicket.id)
            .filter(MaintenanceTicket.status != "closed")
            .label("open"),
        )
        .where(
            MaintenanceTicket.organization_id.in_(org_ids),
            MaintenanceTicket.is_deleted.is_(False),
        )
        .group_by(MaintenanceTicket.organization_id)
    )
    tickets: dict[uuid.UUID, dict] = {}
    for r in ticket_rows.all():
        tickets[r[0]] = {"total": r[1], "open": r[2]}

    result: dict[uuid.UUID, dict] = {}
    for oid in org_ids:
        result[oid] = {
            "seat_count": seats.get(oid, 0),
            "ticket_count": tickets.get(oid, {}).get("total", 0),
            "open_ticket_count": tickets.get(oid, {}).get("open", 0),
        }
    return result


def _risk_label(org: Organization, stats: dict) -> str:
    """Compute a simple risk label for an org."""
    now = datetime.now(timezone.utc)
    if not org.is_active:
        return "inactive"
    if org.payment_status == "past_due":
        return "past_due"
    if org.trial_ends_at and org.trial_ends_at - now <= timedelta(days=7):
        return "trial_expiring"
    if org.payment_status == "canceled":
        return "canceled"
    return "healthy"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedOrgs)
async def list_orgs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    plan: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    stmt = select(Organization)
    if search:
        stmt = stmt.where(Organization.name.ilike(f"%{search}%"))
    if plan:
        stmt = stmt.where(Organization.plan == plan)
    if is_active is not None:
        stmt = stmt.where(Organization.is_active == is_active)
    if payment_status:
        stmt = stmt.where(Organization.payment_status == payment_status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(Organization.created_at.desc()).offset(offset).limit(page_size))
    orgs = result.scalars().all()

    org_ids = [o.id for o in orgs]
    stats = await _org_stats(db, org_ids)

    items = [
        OrgListItem(
            id=o.id,
            name=o.name,
            slug=o.slug,
            plan=o.plan,
            is_active=o.is_active,
            payment_status=o.payment_status,
            max_seats=o.max_seats,
            seat_count=stats.get(o.id, {}).get("seat_count", 0),
            ticket_count=stats.get(o.id, {}).get("ticket_count", 0),
            trial_ends_at=o.trial_ends_at,
            created_at=o.created_at,
        )
        for o in orgs
    ]
    return PaginatedOrgs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.get("/export")
async def export_orgs(
    search: str | None = Query(default=None),
    plan: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    """Export all matching organizations to CSV."""
    stmt = select(Organization)
    if search:
        stmt = stmt.where(Organization.name.ilike(f"%{search}%"))
    if plan:
        stmt = stmt.where(Organization.plan == plan)
    if is_active is not None:
        stmt = stmt.where(Organization.is_active == is_active)
    if payment_status:
        stmt = stmt.where(Organization.payment_status == payment_status)

    result = await db.execute(stmt.order_by(Organization.created_at.desc()))
    orgs = result.scalars().all()

    org_ids = [o.id for o in orgs]
    stats = await _org_stats(db, org_ids)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "slug", "plan", "is_active", "payment_status",
        "max_seats", "seat_count", "ticket_count", "open_tickets",
        "trial_ends_at", "stripe_customer_id", "stripe_subscription_id", "created_at",
    ])
    for o in orgs:
        s = stats.get(o.id, {})
        writer.writerow([
            o.id, o.name, o.slug, o.plan, o.is_active, o.payment_status,
            o.max_seats, s.get("seat_count", 0), s.get("ticket_count", 0), s.get("open_ticket_count", 0),
            o.trial_ends_at, o.stripe_customer_id, o.stripe_subscription_id, o.created_at,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=organizations.csv"},
    )


@router.get("/{org_id}", response_model=OrgDetail)
async def get_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    stats = await _org_stats(db, [org_id])
    s = stats.get(org_id, {})

    return OrgDetail(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        is_active=org.is_active,
        payment_status=org.payment_status,
        max_seats=org.max_seats,
        seat_count=s.get("seat_count", 0),
        ticket_count=s.get("ticket_count", 0),
        open_ticket_count=s.get("open_ticket_count", 0),
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        trial_ends_at=org.trial_ends_at,
        onboarding_complete=org.onboarding_complete,
        admin_notes=org.admin_notes,
        created_at=org.created_at,
    )


@router.patch("/{org_id}", response_model=OrgDetail)
async def patch_org(
    org_id: uuid.UUID,
    payload: OrgPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(org, field, value)

    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes=payload.model_dump(exclude_unset=True),
    )

    stats = await _org_stats(db, [org_id])
    s = stats.get(org_id, {})

    return OrgDetail(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        is_active=org.is_active,
        payment_status=org.payment_status,
        max_seats=org.max_seats,
        seat_count=s.get("seat_count", 0),
        ticket_count=s.get("ticket_count", 0),
        open_ticket_count=s.get("open_ticket_count", 0),
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        trial_ends_at=org.trial_ends_at,
        onboarding_complete=org.onboarding_complete,
        admin_notes=org.admin_notes,
        created_at=org.created_at,
    )


@router.post("/{org_id}/impersonate", response_model=ImpersonateResponse)
async def impersonate_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    """Mint a 1-hour JWT for the org's first active admin. Logged to activity_log."""
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    target = (
        await db.execute(
            select(User)
            .where(
                User.organization_id == org_id,
                User.role == "admin",
                User.is_active.is_(True),
            )
            .order_by(User.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active admin found for this organization",
        )

    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {
            "sub": str(target.id),
            "role": target.role,
            "org_id": str(target.organization_id),
            "is_super_admin": False,
            "impersonated_by": str(current_user.id),
            "exp": expire,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    await log_activity(
        db,
        user=current_user,
        action="impersonated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes={"target_user_id": str(target.id), "target_email": target.email},
    )

    return ImpersonateResponse(
        token=token,
        impersonated_user_id=str(target.id),
        impersonated_user_email=target.email,
    )

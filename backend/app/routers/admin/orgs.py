"""Admin-console organization management and Org 360 views."""
import csv
import io
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from jose import jwt
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_console_role, require_super_admin
from app.config import settings
from app.database import get_db
from app.models.activity_log import ActivityLog
from app.models.billing_ledger import (
    BillingCharge,
    BillingCredit,
    BillingInvoice,
    BillingRefund,
    BillingSubscription,
)
from app.models.impersonation_session import ImpersonationSession
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.office import Office
from app.models.organization import Organization
from app.models.resident import ResidentLease
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.services import entitlements as ent
from app.services import categories as cat
from app.services import lease_limits
from app.services import org_health, usage_service
from app.services.stripe_settings import resolve_stripe_secret_key
from app.services.activity_service import log_activity
from app.services.console_roles import resolve_console_role

router = APIRouter()
logger = logging.getLogger(__name__)

PLAN_RANK = {"starter": 0, "pro": 1, "enterprise": 2}


class OrgHealth(BaseModel):
    score: int
    band: str
    factors: dict


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
    risk_label: str
    health_score: int
    health_band: str

    model_config = {"from_attributes": True}


class OrgTimelineEntry(BaseModel):
    source: str
    kind: str
    title: str
    description: str | None = None
    occurred_at: datetime
    meta: dict | None = None


class OrgDetail(OrgListItem):
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    onboarding_complete: bool
    open_ticket_count: int
    admin_notes: str | None
    office_count: int
    active_lease_count: int = 0
    entitlement_overrides: dict
    plan_defaults: dict
    effective_entitlements: dict
    categories: dict = Field(default_factory=dict)
    health_factors: dict
    timeline: list[OrgTimelineEntry] = Field(default_factory=list)


class OrgPatch(BaseModel):
    name: str | None = None
    plan: str | None = None
    is_active: bool | None = None
    max_seats: int | None = None
    payment_status: str | None = None
    trial_ends_at: datetime | None = None
    onboarding_complete: bool | None = None
    admin_notes: str | None = None
    entitlement_overrides: dict | None = None
    category_overrides: dict | None = None


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


class BulkOrgActionRequest(BaseModel):
    org_ids: list[uuid.UUID]
    action: str
    reason: str | None = None
    plan: str | None = None
    message: str | None = None


class BulkOrgActionResponse(BaseModel):
    action: str
    updated_count: int
    org_ids: list[uuid.UUID]


async def _org_stats(db: AsyncSession, org_ids: list[uuid.UUID], orgs_by_id: dict[uuid.UUID, Organization]) -> dict[uuid.UUID, dict]:
    if not org_ids:
        return {}

    seat_rows = await db.execute(
        select(
            User.organization_id,
            func.count(User.id).label("cnt"),
            func.max(User.last_login_at).label("last_login_at"),
        )
        .where(User.organization_id.in_(org_ids), User.is_active.is_(True))
        .group_by(User.organization_id)
    )
    seats = {r[0]: {"seat_count": r[1], "last_login_at": r[2]} for r in seat_rows.all()}

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
    tickets = {r[0]: {"ticket_count": r[1], "open_ticket_count": r[2]} for r in ticket_rows.all()}

    office_rows = await db.execute(
        select(Office.organization_id, func.count(Office.id).label("cnt"))
        .where(Office.organization_id.in_(org_ids), Office.is_deleted.is_(False))
        .group_by(Office.organization_id)
    )
    offices = {r[0]: r[1] for r in office_rows.all()}

    # Active leases toward the plan cap: commercial (non-terminal) + residential.
    commercial_lease_rows = await db.execute(
        select(Lease.organization_id, func.count(Lease.id).label("cnt"))
        .where(
            Lease.organization_id.in_(org_ids),
            Lease.is_deleted.is_(False),
            or_(
                Lease.status.is_(None),
                func.lower(Lease.status).notin_(
                    lease_limits.INACTIVE_COMMERCIAL_STATUSES
                ),
            ),
        )
        .group_by(Lease.organization_id)
    )
    active_leases = {r[0]: int(r[1]) for r in commercial_lease_rows.all()}
    resident_lease_rows = await db.execute(
        select(ResidentLease.organization_id, func.count(ResidentLease.id).label("cnt"))
        .where(
            ResidentLease.organization_id.in_(org_ids),
            ResidentLease.is_deleted.is_(False),
            func.lower(ResidentLease.status).in_(lease_limits.ACTIVE_RESIDENT_STATUSES),
        )
        .group_by(ResidentLease.organization_id)
    )
    for oid, cnt in ((r[0], int(r[1])) for r in resident_lease_rows.all()):
        active_leases[oid] = active_leases.get(oid, 0) + cnt

    activity_rows = await db.execute(
        select(ActivityLog.entity_id, func.max(ActivityLog.created_at).label("last_activity_at"))
        .where(
            ActivityLog.entity_type == "organization",
            ActivityLog.entity_id.in_(org_ids),
        )
        .group_by(ActivityLog.entity_id)
    )
    activities = {r[0]: r[1] for r in activity_rows.all()}

    current_period = usage_service.current_period()
    previous_period = usage_service.previous_period()
    token_rows = await db.execute(
        select(
            UsageEvent.organization_id,
            UsageEvent.period_month,
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        )
        .where(
            UsageEvent.organization_id.in_(org_ids),
            UsageEvent.period_month.in_([current_period, previous_period]),
        )
        .group_by(UsageEvent.organization_id, UsageEvent.period_month)
    )
    token_map: dict[uuid.UUID, dict[str, int]] = {}
    for org_id, period_month, input_tokens, output_tokens in token_rows.all():
        cur = token_map.setdefault(org_id, {})
        cur[f"{period_month}_input"] = int(input_tokens)
        cur[f"{period_month}_output"] = int(output_tokens)

    result: dict[uuid.UUID, dict] = {}
    now = datetime.now(timezone.utc)
    for oid in org_ids:
        org = orgs_by_id[oid]
        seat_data = seats.get(oid, {})
        ticket_data = tickets.get(oid, {})
        token_data = token_map.get(oid, {})
        stats = {
            "seat_count": int(seat_data.get("seat_count", 0)),
            "last_login_at": seat_data.get("last_login_at"),
            "ticket_count": int(ticket_data.get("ticket_count", 0)),
            "open_ticket_count": int(ticket_data.get("open_ticket_count", 0)),
            "office_count": int(offices.get(oid, 0)),
            "active_lease_count": int(active_leases.get(oid, 0)),
            "last_activity_at": activities.get(oid),
            "current_total_tokens": token_data.get(f"{current_period}_input", 0) + token_data.get(f"{current_period}_output", 0),
            "previous_total_tokens": token_data.get(f"{previous_period}_input", 0) + token_data.get(f"{previous_period}_output", 0),
            "effective_max_seats": ent.get_limit(org, "max_seats"),
            "now": now,
        }
        stats["health"] = org_health.compute_health_score(org, stats)
        result[oid] = stats
    return result


def _risk_label(org: Organization, stats: dict) -> str:
    health = stats.get("health") or {"band": "healthy"}
    now = datetime.now(timezone.utc)
    if not org.is_active:
        return "inactive"
    if org.payment_status == "past_due":
        return "past_due"
    if org.payment_status == "canceled":
        return "canceled"
    if org.trial_ends_at and org.trial_ends_at - now <= timedelta(days=7):
        return "trial_expiring"
    return health.get("band", "healthy")


async def _timeline_for_org(db: AsyncSession, org_id: uuid.UUID, limit: int = 60) -> list[OrgTimelineEntry]:
    activity_rows = (
        await db.execute(
            select(ActivityLog)
            .where(
                or_(
                    ActivityLog.organization_id == org_id,
                    (ActivityLog.entity_type == "organization") & (ActivityLog.entity_id == org_id),
                )
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    subs = (
        await db.execute(
            select(BillingSubscription)
            .where(BillingSubscription.organization_id == org_id)
            .order_by(BillingSubscription.updated_at.desc())
            .limit(12)
        )
    ).scalars().all()
    invoices = (
        await db.execute(
            select(BillingInvoice)
            .where(BillingInvoice.organization_id == org_id)
            .order_by(BillingInvoice.issued_at.desc().nullslast())
            .limit(12)
        )
    ).scalars().all()
    charges = (
        await db.execute(
            select(BillingCharge)
            .where(BillingCharge.organization_id == org_id)
            .order_by(BillingCharge.charged_at.desc().nullslast())
            .limit(12)
        )
    ).scalars().all()
    refunds = (
        await db.execute(
            select(BillingRefund)
            .where(BillingRefund.organization_id == org_id)
            .order_by(BillingRefund.refunded_at.desc().nullslast())
            .limit(12)
        )
    ).scalars().all()
    credits = (
        await db.execute(
            select(BillingCredit)
            .where(BillingCredit.organization_id == org_id)
            .order_by(BillingCredit.created_at.desc())
            .limit(12)
        )
    ).scalars().all()

    timeline: list[OrgTimelineEntry] = []
    for row in activity_rows:
        timeline.append(
            OrgTimelineEntry(
                source="activity_log",
                kind=row.action,
                title=f"{row.user_display_name} {row.action} {row.entity_type.replace('_', ' ')}",
                description=row.entity_label,
                occurred_at=row.created_at,
                meta=row.changes,
            )
        )
    for row in subs:
        when = row.canceled_at or row.current_period_end or row.updated_at
        timeline.append(
            OrgTimelineEntry(
                source="billing_subscription",
                kind=row.status,
                title=f"Subscription {row.status}",
                description=f"{row.plan or 'unknown'} · ${((row.amount_cents or 0) / 100):,.0f}/{row.interval}",
                occurred_at=when,
                meta={"quantity": row.quantity, "status": row.status},
            )
        )
    for row in invoices:
        if row.issued_at:
            timeline.append(
                OrgTimelineEntry(
                    source="billing_invoice",
                    kind=row.status,
                    title=f"Invoice {row.number or row.id}",
                    description=f"{row.status} · ${((row.total_cents or 0) / 100):,.2f}",
                    occurred_at=row.issued_at,
                    meta={"amount_due_cents": row.amount_due_cents, "amount_paid_cents": row.amount_paid_cents},
                )
            )
    for row in charges:
        if row.charged_at:
            timeline.append(
                OrgTimelineEntry(
                    source="billing_charge",
                    kind=row.status,
                    title=f"Charge {row.status}",
                    description=f"${((row.amount_cents or 0) / 100):,.2f}",
                    occurred_at=row.charged_at,
                    meta={"amount_refunded_cents": row.amount_refunded_cents},
                )
            )
    for row in refunds:
        if row.refunded_at:
            timeline.append(
                OrgTimelineEntry(
                    source="billing_refund",
                    kind=row.status,
                    title="Refund issued",
                    description=f"${((row.amount_cents or 0) / 100):,.2f}",
                    occurred_at=row.refunded_at,
                    meta={"reason": row.reason},
                )
            )
    for row in credits:
        timeline.append(
            OrgTimelineEntry(
                source="billing_credit",
                kind="credit",
                title="Manual credit",
                description=f"${((row.amount_cents or 0) / 100):,.2f}",
                occurred_at=row.created_at,
                meta={"reason": row.reason},
            )
        )

    timeline.sort(key=lambda item: item.occurred_at, reverse=True)
    return timeline[:limit]


async def _build_detail(db: AsyncSession, org: Organization, stats: dict[uuid.UUID, dict]) -> OrgDetail:
    s = stats.get(org.id, {})
    health = s.get("health") or org_health.compute_health_score(org, s)
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
        office_count=s.get("office_count", 0),
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        trial_ends_at=org.trial_ends_at,
        onboarding_complete=org.onboarding_complete,
        admin_notes=org.admin_notes,
        created_at=org.created_at,
        active_lease_count=s.get("active_lease_count", 0),
        risk_label=_risk_label(org, s),
        health_score=health["score"],
        health_band=health["band"],
        health_factors=health["factors"],
        entitlement_overrides=ent.normalize_overrides(org.entitlement_overrides),
        plan_defaults=ent.plan_entitlements(org.plan),
        effective_entitlements=ent.effective_entitlements(org),
        categories=cat.categories_state(org),
        timeline=await _timeline_for_org(db, org.id),
    )


@router.get("", response_model=PaginatedOrgs)
async def list_orgs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    plan: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
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
    orgs_by_id = {o.id: o for o in orgs}
    stats = await _org_stats(db, [o.id for o in orgs], orgs_by_id)

    items = []
    for org in orgs:
        health = stats.get(org.id, {}).get("health") or {"score": 0, "band": "critical"}
        items.append(
            OrgListItem(
                id=org.id,
                name=org.name,
                slug=org.slug,
                plan=org.plan,
                is_active=org.is_active,
                payment_status=org.payment_status,
                max_seats=org.max_seats,
                seat_count=stats.get(org.id, {}).get("seat_count", 0),
                ticket_count=stats.get(org.id, {}).get("ticket_count", 0),
                trial_ends_at=org.trial_ends_at,
                created_at=org.created_at,
                risk_label=_risk_label(org, stats.get(org.id, {})),
                health_score=health["score"],
                health_band=health["band"],
            )
        )
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
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
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

    result = await db.execute(stmt.order_by(Organization.created_at.desc()))
    orgs = result.scalars().all()
    orgs_by_id = {o.id: o for o in orgs}
    stats = await _org_stats(db, [o.id for o in orgs], orgs_by_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "slug", "plan", "is_active", "payment_status",
        "max_seats", "seat_count", "ticket_count", "health_score", "health_band",
        "trial_ends_at", "stripe_customer_id", "stripe_subscription_id", "created_at",
    ])
    for org in orgs:
        s = stats.get(org.id, {})
        health = s.get("health") or {"score": 0, "band": "critical"}
        writer.writerow([
            org.id, org.name, org.slug, org.plan, org.is_active, org.payment_status,
            org.max_seats, s.get("seat_count", 0), s.get("ticket_count", 0), health["score"], health["band"],
            org.trial_ends_at, org.stripe_customer_id, org.stripe_subscription_id, org.created_at,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=organizations.csv"},
    )


@router.post("/bulk-actions", response_model=BulkOrgActionResponse)
async def bulk_org_actions(
    payload: BulkOrgActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    if not payload.org_ids:
        raise HTTPException(status_code=422, detail="At least one organization is required")
    orgs = (
        await db.execute(select(Organization).where(Organization.id.in_(payload.org_ids)))
    ).scalars().all()
    if len(orgs) != len(set(payload.org_ids)):
        raise HTTPException(status_code=404, detail="One or more organizations were not found")

    role = await resolve_console_role(db, current_user)
    assert role is not None
    updated: list[uuid.UUID] = []

    for org in orgs:
        if payload.action == "suspend":
            if role not in {"super_admin", "support"}:
                raise HTTPException(status_code=403, detail="Suspension requires support or super-admin access")
            if not (payload.reason or "").strip():
                raise HTTPException(status_code=422, detail="A reason is required when suspending organizations")
            org.is_active = False
            await db.commit()
            await log_activity(
                db,
                user=current_user,
                action="updated",
                entity_type="organization",
                entity_id=org.id,
                entity_label=org.name,
                changes={"action": "bulk_suspend", "reason": payload.reason},
            )
            updated.append(org.id)
        elif payload.action == "change_plan":
            if role not in {"super_admin", "finance"}:
                raise HTTPException(status_code=403, detail="Plan changes require finance or super-admin access")
            if payload.plan not in ent.PLAN_CATALOG:
                raise HTTPException(status_code=422, detail="A valid target plan is required")
            is_downgrade = PLAN_RANK.get(payload.plan or "", -1) < PLAN_RANK.get(org.plan or "", -1)
            if is_downgrade and not (payload.reason or "").strip():
                raise HTTPException(status_code=422, detail="A reason is required when downgrading a plan")
            old_plan = org.plan
            org.plan = payload.plan or org.plan
            await db.commit()
            await log_activity(
                db,
                user=current_user,
                action="updated",
                entity_type="organization",
                entity_id=org.id,
                entity_label=org.name,
                changes={"action": "bulk_plan_change", "old_plan": old_plan, "new_plan": org.plan, "reason": payload.reason},
            )
            updated.append(org.id)
        elif payload.action == "send_message":
            if role not in {"super_admin", "support"}:
                raise HTTPException(status_code=403, detail="Messaging requires support or super-admin access")
            message = (payload.message or "").strip()
            if not message:
                raise HTTPException(status_code=422, detail="A message is required")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            note = f"[{timestamp}] Outreach: {message}"
            org.admin_notes = f"{org.admin_notes}\n\n{note}".strip() if org.admin_notes else note
            await db.commit()
            await log_activity(
                db,
                user=current_user,
                action="updated",
                entity_type="organization",
                entity_id=org.id,
                entity_label=org.name,
                changes={"action": "bulk_send_message", "message": message},
            )
            updated.append(org.id)
        else:
            raise HTTPException(status_code=422, detail="Unsupported bulk action")

    return BulkOrgActionResponse(action=payload.action, updated_count=len(updated), org_ids=updated)


@router.get("/{org_id}/timeline", response_model=list[OrgTimelineEntry])
async def get_org_timeline(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    return await _timeline_for_org(db, org_id)


@router.get("/{org_id}", response_model=OrgDetail)
async def get_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    stats = await _org_stats(db, [org_id], {org_id: org})
    return await _build_detail(db, org, stats)


@router.patch("/{org_id}", response_model=OrgDetail)
async def patch_org(
    org_id: uuid.UUID,
    payload: OrgPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    role = await resolve_console_role(db, current_user)
    assert role is not None
    data = payload.model_dump(exclude_unset=True)
    prior_entitlement_overrides = org.entitlement_overrides
    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Organization name cannot be empty.")
        data["name"] = new_name
    if "plan" in data and data["plan"] not in ent.PLAN_CATALOG:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown plan '{data['plan']}'.")
    if "entitlement_overrides" in data:
        data["entitlement_overrides"] = ent.normalize_overrides(data["entitlement_overrides"])
    if "category_overrides" in data:
        if role != "super_admin":
            raise HTTPException(status_code=403, detail="Category overrides require super-admin access")
        normalized_cat = cat.normalize_overrides(data["category_overrides"])
        # Validate the resulting effective set keeps at least one category on.
        probe = Organization(
            enabled_categories=cat.normalize_enabled(org.enabled_categories),
            category_overrides=normalized_cat,
        )
        if not cat.effective_enabled_categories(probe):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least one primary category must remain enabled.",
            )
        data["category_overrides"] = normalized_cat

    billing_fields = {"plan", "payment_status", "trial_ends_at"}
    support_fields = {"name", "admin_notes", "onboarding_complete", "max_seats", "entitlement_overrides"}
    super_admin_fields = {"category_overrides"}
    if billing_fields & data.keys() and role not in {"super_admin", "finance"}:
        raise HTTPException(status_code=403, detail="Billing changes require finance or super-admin access")
    if {"is_active"} & data.keys() and role not in {"super_admin", "support"}:
        raise HTTPException(status_code=403, detail="Suspension changes require support or super-admin access")
    if set(data.keys()) - billing_fields - support_fields - super_admin_fields - {"is_active"}:
        raise HTTPException(status_code=403, detail="Unsupported organization update")

    for field, value in data.items():
        setattr(org, field, value)

    await db.commit()
    audit_changes = dict(data)
    if "entitlement_overrides" in data:
        audit_changes["entitlement_overrides"] = {
            "before": ent.normalize_overrides(prior_entitlement_overrides),
            "after": data["entitlement_overrides"],
        }
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes=audit_changes,
    )
    stats = await _org_stats(db, [org_id], {org_id: org})
    return await _build_detail(db, org, stats)


@router.get("/{org_id}/catalog")
async def get_catalog(
    org_id: uuid.UUID,
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    return {
        "plans": list(ent.PLAN_CATALOG.keys()),
        "limit_keys": list(ent.LIMIT_KEYS),
        "feature_keys": list(ent.FEATURE_KEYS),
        "catalog": ent.PLAN_CATALOG,
    }


@router.post("/{org_id}/impersonate", response_model=ImpersonateResponse)
async def impersonate_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "support")),
):
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active admin found for this organization")

    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {
            "sub": str(target.id),
            "role": target.role,
            "org_id": str(target.organization_id),
            "is_super_admin": False,
            "console_role": None,
            "impersonated_by": str(current_user.id),
            "exp": expire,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    db.add(
        ImpersonationSession(
            admin_user_id=current_user.id,
            target_org_id=org_id,
            target_user_id=target.id,
            target_user_email=target.email,
            expires_at=expire,
        )
    )
    await db.commit()
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


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    stripe_key = await resolve_stripe_secret_key(db)
    if org.stripe_subscription_id and stripe_key:
        try:
            import stripe
            stripe.api_key = stripe_key
            stripe.Subscription.delete(org.stripe_subscription_id)
        except Exception as exc:  # pragma: no cover - network best effort
            logger.warning("Failed to cancel Stripe subscription on org delete: %s", exc)

    org.is_active = False
    org.payment_status = "canceled"
    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="deleted",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes={"is_active": False, "payment_status": "canceled"},
    )

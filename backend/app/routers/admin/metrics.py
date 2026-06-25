"""Super-admin: platform-wide KPI metrics."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.organization import Organization
from app.models.user import User

router = APIRouter()


class PlanBreakdown(BaseModel):
    starter: int
    pro: int
    enterprise: int


class PlatformMetrics(BaseModel):
    total_orgs: int
    active_orgs: int
    trial_orgs: int
    past_due_orgs: int
    new_orgs_30d: int
    orgs_by_plan: PlanBreakdown
    total_users: int
    active_users: int
    total_tickets: int
    open_tickets: int
    # Revenue estimates based on plan tiers (starter=$99, pro=$299, enterprise=$999)
    mrr_cents: int
    arr_cents: int

# Per-plan monthly price in cents (active + past_due orgs only)
_PLAN_PRICE_CENTS = {"starter": 9900, "pro": 29900, "enterprise": 99900}


@router.get("", response_model=PlatformMetrics)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)

    # All org aggregates in one pass
    org_rows = await db.execute(
        select(
            func.count(Organization.id).label("total"),
            func.count(Organization.id).filter(Organization.is_active.is_(True)).label("active"),
            func.count(Organization.id).filter(
                Organization.trial_ends_at.is_not(None),
                Organization.trial_ends_at >= now,
            ).label("trial"),
            func.count(Organization.id).filter(Organization.payment_status == "past_due").label("past_due"),
            func.count(Organization.id).filter(Organization.created_at >= cutoff_30d).label("new_30d"),
            func.count(Organization.id).filter(Organization.plan == "starter").label("starter"),
            func.count(Organization.id).filter(Organization.plan == "pro").label("pro"),
            func.count(Organization.id).filter(Organization.plan == "enterprise").label("enterprise"),
            # Revenue-eligible orgs by plan (active or past_due — not trial/canceled)
            func.count(Organization.id).filter(
                Organization.plan == "starter",
                Organization.payment_status.in_(["active", "past_due"]),
            ).label("rev_starter"),
            func.count(Organization.id).filter(
                Organization.plan == "pro",
                Organization.payment_status.in_(["active", "past_due"]),
            ).label("rev_pro"),
            func.count(Organization.id).filter(
                Organization.plan == "enterprise",
                Organization.payment_status.in_(["active", "past_due"]),
            ).label("rev_enterprise"),
        )
    )
    org_agg = org_rows.one()

    # User aggregates
    user_rows = await db.execute(
        select(
            func.count(User.id).label("total"),
            func.count(User.id).filter(User.is_active.is_(True)).label("active"),
        )
    )
    user_agg = user_rows.one()

    # Ticket aggregates
    ticket_rows = await db.execute(
        select(
            func.count(MaintenanceTicket.id).label("total"),
            func.count(MaintenanceTicket.id).filter(
                MaintenanceTicket.status != "closed",
                MaintenanceTicket.is_deleted.is_(False),
            ).label("open"),
        ).where(MaintenanceTicket.is_deleted.is_(False))
    )
    ticket_agg = ticket_rows.one()

    mrr_cents = (
        org_agg.rev_starter * _PLAN_PRICE_CENTS["starter"]
        + org_agg.rev_pro * _PLAN_PRICE_CENTS["pro"]
        + org_agg.rev_enterprise * _PLAN_PRICE_CENTS["enterprise"]
    )

    return PlatformMetrics(
        total_orgs=org_agg.total,
        active_orgs=org_agg.active,
        trial_orgs=org_agg.trial,
        past_due_orgs=org_agg.past_due,
        new_orgs_30d=org_agg.new_30d,
        orgs_by_plan=PlanBreakdown(
            starter=org_agg.starter,
            pro=org_agg.pro,
            enterprise=org_agg.enterprise,
        ),
        total_users=user_agg.total,
        active_users=user_agg.active,
        total_tickets=ticket_agg.total,
        open_tickets=ticket_agg.open,
        mrr_cents=mrr_cents,
        arr_cents=mrr_cents * 12,
    )

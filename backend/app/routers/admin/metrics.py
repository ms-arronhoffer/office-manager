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
from app.tasks.job_status import registry as job_registry
from app.tasks.scheduler import scheduler
from app.services import revenue_service

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
    # True if mrr/arr are derived from the persisted billing ledger (real Stripe
    # data) rather than the plan-count price estimate.
    mrr_from_ledger: bool = False
    # At-risk breakdowns
    at_risk_trial_expiring: int
    at_risk_past_due: int
    at_risk_canceled: int
    at_risk_inactive: int

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
            # At-risk breakdowns
            func.count(Organization.id).filter(
                Organization.trial_ends_at.is_not(None),
                Organization.trial_ends_at >= now,
                Organization.trial_ends_at <= now + timedelta(days=7),
                Organization.stripe_subscription_id.is_(None),
            ).label("trial_expiring_7d"),
            func.count(Organization.id).filter(
                Organization.payment_status == "past_due",
            ).label("at_risk_past_due"),
            func.count(Organization.id).filter(
                Organization.payment_status == "canceled",
            ).label("at_risk_canceled"),
            func.count(Organization.id).filter(
                Organization.is_active.is_(False),
            ).label("at_risk_inactive"),
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
    # Prefer real ledger-derived MRR when the billing ledger has data; otherwise
    # fall back to the plan-count price estimate above.
    ledger_mrr = await revenue_service.mrr_from_ledger(db)
    from_ledger = ledger_mrr > 0
    if from_ledger:
        mrr_cents = ledger_mrr

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
        mrr_from_ledger=from_ledger,
        at_risk_trial_expiring=org_agg.trial_expiring_7d,
        at_risk_past_due=org_agg.at_risk_past_due,
        at_risk_canceled=org_agg.at_risk_canceled,
        at_risk_inactive=org_agg.at_risk_inactive,
    )


class ScheduledJob(BaseModel):
    job_id: str
    next_run_at: str | None = None
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_duration_ms: int | None = None
    run_count: int = 0
    failure_count: int = 0


class ScheduledJobsResponse(BaseModel):
    scheduler_running: bool
    jobs: list[ScheduledJob]


@router.get("/jobs", response_model=ScheduledJobsResponse)
async def get_scheduled_jobs(
    _: User = Depends(require_super_admin()),
):
    """Operational view of background scheduler jobs: their next scheduled run
    plus the last execution outcome (status, error, duration) recorded by the
    in-memory job-status registry. Lets operators confirm reminders, billing
    hygiene, webhook retries, etc. are running and succeeding."""
    status_by_id = {row["job_id"]: row for row in job_registry.snapshot()}

    next_run_by_id: dict[str, str | None] = {}
    for job in scheduler.get_jobs():
        nrt = getattr(job, "next_run_time", None)
        next_run_by_id[job.id] = nrt.isoformat() if nrt else None

    # Union of jobs known to the scheduler and jobs that have recorded status.
    job_ids = sorted(set(status_by_id) | set(next_run_by_id))
    jobs = [
        ScheduledJob(
            job_id=jid,
            next_run_at=next_run_by_id.get(jid),
            **{k: v for k, v in status_by_id.get(jid, {}).items() if k != "job_id"},
        )
        for jid in job_ids
    ]
    return ScheduledJobsResponse(scheduler_running=scheduler.running, jobs=jobs)


class RevenueMetrics(BaseModel):
    mrr_cents: int
    arr_cents: int
    collected_cents: int
    refunded_cents: int
    failed_cents: int
    net_cents: int
    window_days: int
    plan_breakdown: list[dict]
    timeseries: list[dict]


@router.get("/revenue", response_model=RevenueMetrics)
async def get_revenue(
    window_days: int = 30,
    months: int = 12,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    """Ledger-driven revenue analytics: real MRR/ARR, collected/refunded/failed
    over a window, plan mix, and a monthly collected time-series. Sourced from
    the persisted billing ledger (Stripe-synced), not plan-count estimates."""
    mrr = await revenue_service.mrr_from_ledger(db)
    summary = await revenue_service.collected_summary(db, days=window_days)
    return RevenueMetrics(
        mrr_cents=mrr,
        arr_cents=mrr * 12,
        collected_cents=summary["collected_cents"],
        refunded_cents=summary["refunded_cents"],
        failed_cents=summary["failed_cents"],
        net_cents=summary["net_cents"],
        window_days=summary["window_days"],
        plan_breakdown=await revenue_service.plan_breakdown(db),
        timeseries=await revenue_service.revenue_timeseries(db, months=months),
    )

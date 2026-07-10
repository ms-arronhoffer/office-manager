"""Admin-console KPI and analytics metrics."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_console_role
from app.database import get_db
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.organization import Organization
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.tasks.job_status import registry as job_registry
from app.tasks.scheduler import scheduler
from app.services import entitlements as ent
from app.services import revenue_service

router = APIRouter()

INPUT_TOKEN_COST_PER_MILLION_CENTS = 300
OUTPUT_TOKEN_COST_PER_MILLION_CENTS = 1200


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
    mrr_cents: int
    arr_cents: int
    mrr_from_ledger: bool = False
    at_risk_trial_expiring: int
    at_risk_past_due: int
    at_risk_canceled: int
    at_risk_inactive: int


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


class MrrTrendPoint(BaseModel):
    period: str
    mrr_cents: int
    arr_cents: int


class OrgMovementPoint(BaseModel):
    period: str
    new_orgs: int
    churned_orgs: int


class TokenSpendPoint(BaseModel):
    period: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_spend_cents: int


class FunnelStage(BaseModel):
    stage: str
    count: int


@router.get("", response_model=PlatformMetrics)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
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
            func.count(Organization.id).filter(
                Organization.trial_ends_at.is_not(None),
                Organization.trial_ends_at >= now,
                Organization.trial_ends_at <= now + timedelta(days=7),
                Organization.stripe_subscription_id.is_(None),
            ).label("trial_expiring_7d"),
            func.count(Organization.id).filter(Organization.payment_status == "past_due").label("at_risk_past_due"),
            func.count(Organization.id).filter(Organization.payment_status == "canceled").label("at_risk_canceled"),
            func.count(Organization.id).filter(Organization.is_active.is_(False)).label("at_risk_inactive"),
        )
    )
    org_agg = org_rows.one()
    user_rows = await db.execute(
        select(
            func.count(User.id).label("total"),
            func.count(User.id).filter(User.is_active.is_(True)).label("active"),
        )
    )
    user_agg = user_rows.one()
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
        org_agg.rev_starter * ent.PLAN_PRICE_CENTS["starter"]
        + org_agg.rev_pro * ent.PLAN_PRICE_CENTS["pro"]
        + org_agg.rev_enterprise * ent.PLAN_PRICE_CENTS["enterprise"]
    )
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


@router.get("/mrr-trend", response_model=list[MrrTrendPoint])
async def get_mrr_trend(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    rows = (
        await db.execute(
            text(
                """
                WITH months AS (
                    SELECT generate_series(
                        date_trunc('month', now()) - interval '11 months',
                        date_trunc('month', now()),
                        interval '1 month'
                    ) AS month_start
                ),
                org_ranges AS (
                    SELECT
                        created_at,
                        CASE plan
                            WHEN 'starter' THEN :starter
                            WHEN 'pro' THEN :pro
                            WHEN 'enterprise' THEN :enterprise
                            ELSE 0
                        END AS price_cents,
                        CASE
                            WHEN payment_status = 'canceled' THEN updated_at
                            ELSE NULL
                        END AS ended_at,
                        payment_status
                    FROM organizations
                )
                SELECT
                    to_char(m.month_start, 'YYYY-MM') AS period,
                    COALESCE(SUM(
                        CASE
                            WHEN o.created_at < (m.month_start + interval '1 month')
                             AND (o.ended_at IS NULL OR o.ended_at >= m.month_start)
                             AND o.payment_status IN ('active', 'past_due', 'canceled')
                            THEN o.price_cents
                            ELSE 0
                        END
                    ), 0) AS mrr_cents
                FROM months m
                LEFT JOIN org_ranges o ON TRUE
                GROUP BY m.month_start
                ORDER BY m.month_start
                """
            ),
            ent.PLAN_PRICE_CENTS,
        )
    ).all()
    return [MrrTrendPoint(period=row[0], mrr_cents=int(row[1]), arr_cents=int(row[1]) * 12) for row in rows]


@router.get("/new-vs-churned", response_model=list[OrgMovementPoint])
async def get_new_vs_churned(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    rows = (
        await db.execute(
            text(
                """
                WITH months AS (
                    SELECT generate_series(
                        date_trunc('month', now()) - interval '11 months',
                        date_trunc('month', now()),
                        interval '1 month'
                    ) AS month_start
                ),
                created AS (
                    SELECT date_trunc('month', created_at) AS month_start, count(*) AS cnt
                    FROM organizations
                    WHERE created_at >= date_trunc('month', now()) - interval '11 months'
                    GROUP BY 1
                ),
                churned AS (
                    SELECT date_trunc('month', updated_at) AS month_start, count(*) AS cnt
                    FROM organizations
                    WHERE payment_status = 'canceled'
                      AND updated_at >= date_trunc('month', now()) - interval '11 months'
                    GROUP BY 1
                )
                SELECT
                    to_char(m.month_start, 'YYYY-MM') AS period,
                    COALESCE(c.cnt, 0) AS new_orgs,
                    COALESCE(ch.cnt, 0) AS churned_orgs
                FROM months m
                LEFT JOIN created c ON c.month_start = m.month_start
                LEFT JOIN churned ch ON ch.month_start = m.month_start
                ORDER BY m.month_start
                """
            )
        )
    ).all()
    return [OrgMovementPoint(period=row[0], new_orgs=int(row[1]), churned_orgs=int(row[2])) for row in rows]


@router.get("/token-spend-trend", response_model=list[TokenSpendPoint])
async def get_token_spend_trend(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=31 * 11)).strftime("%Y-%m")
    rows = (
        await db.execute(
            text(
                """
                WITH months AS (
                    SELECT to_char(generate_series(
                        date_trunc('month', now()) - interval '11 months',
                        date_trunc('month', now()),
                        interval '1 month'
                    ), 'YYYY-MM') AS period
                ),
                usage_rollup AS (
                    SELECT
                        period_month,
                        COALESCE(SUM(input_tokens), 0) AS input_tokens,
                        COALESCE(SUM(output_tokens), 0) AS output_tokens
                    FROM usage_events
                    WHERE period_month >= :cutoff
                    GROUP BY period_month
                )
                SELECT
                    m.period,
                    COALESCE(u.input_tokens, 0) AS input_tokens,
                    COALESCE(u.output_tokens, 0) AS output_tokens
                FROM months m
                LEFT JOIN usage_rollup u ON u.period_month = m.period
                ORDER BY m.period
                """
            ),
            {"cutoff": cutoff},
        )
    ).all()
    result: list[TokenSpendPoint] = []
    for period, input_tokens, output_tokens in rows:
        input_tokens = int(input_tokens)
        output_tokens = int(output_tokens)
        spend = int((input_tokens / 1_000_000) * INPUT_TOKEN_COST_PER_MILLION_CENTS + (output_tokens / 1_000_000) * OUTPUT_TOKEN_COST_PER_MILLION_CENTS)
        result.append(
            TokenSpendPoint(
                period=period,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                estimated_spend_cents=spend,
            )
        )
    return result


@router.get("/trial-funnel", response_model=list[FunnelStage])
async def get_trial_funnel(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    now = datetime.now(timezone.utc)
    used_orgs = select(UsageEvent.organization_id).distinct()
    rows = (
        await db.execute(
            select(
                func.count(Organization.id).filter(
                    Organization.trial_ends_at.is_not(None),
                    Organization.trial_ends_at >= now,
                    Organization.stripe_subscription_id.is_(None),
                ).label("trialing"),
                func.count(Organization.id).filter(
                    Organization.trial_ends_at.is_not(None),
                    Organization.trial_ends_at >= now,
                    Organization.stripe_subscription_id.is_(None),
                    Organization.id.in_(used_orgs),
                ).label("engaged"),
                func.count(Organization.id).filter(
                    Organization.trial_ends_at.is_not(None),
                    Organization.stripe_subscription_id.is_not(None),
                ).label("converted"),
                func.count(Organization.id).filter(
                    Organization.trial_ends_at.is_not(None),
                    Organization.trial_ends_at < now,
                    Organization.stripe_subscription_id.is_(None),
                ).label("expired"),
            )
        )
    ).one()
    return [
        FunnelStage(stage="Trial started", count=int(rows.trialing)),
        FunnelStage(stage="Trial engaged", count=int(rows.engaged)),
        FunnelStage(stage="Converted to paid", count=int(rows.converted)),
        FunnelStage(stage="Trial expired", count=int(rows.expired)),
    ]


@router.get("/jobs", response_model=ScheduledJobsResponse)
async def get_scheduled_jobs(
    _: User = Depends(require_console_role("super_admin", "support", "finance")),
):
    status_by_id = {row["job_id"]: row for row in job_registry.snapshot()}
    next_run_by_id: dict[str, str | None] = {}
    for job in scheduler.get_jobs():
        nrt = getattr(job, "next_run_time", None)
        next_run_by_id[job.id] = nrt.isoformat() if nrt else None
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


@router.get("/revenue", response_model=RevenueMetrics)
async def get_revenue(
    window_days: int = 30,
    months: int = 12,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
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

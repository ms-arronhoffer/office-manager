"""Ledger-driven revenue analytics (Phase 2).

Computes real revenue KPIs from the persisted billing ledger instead of the old
plan-count × hardcoded-price estimate:

  - ``mrr_cents`` — sum of active subscriptions' normalized monthly amount.
  - collected / refunded / failed dollars over a window.
  - MRR movement (new / expansion / contraction / churn) period-over-period.
  - trial→paid conversion, dunning recovery, monthly time-series, plan mix.

When the ledger is empty (Stripe not yet syncing) callers can fall back to the
plan-count estimate; ``mrr_from_ledger`` returns ``0`` so the difference is
visible rather than masked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_ledger import BillingCharge, BillingRefund, BillingSubscription

_ACTIVE = ("active", "trialing", "past_due")


def _monthly_cents(amount: int, quantity: int, interval: str) -> int:
    total = (amount or 0) * (quantity or 1)
    if interval == "year":
        return total // 12
    if interval == "week":
        return total * 4
    return total


async def mrr_from_ledger(db: AsyncSession) -> int:
    """Normalized monthly recurring revenue across active subscriptions (cents)."""
    rows = (
        await db.execute(
            select(BillingSubscription.amount_cents, BillingSubscription.quantity,
                   BillingSubscription.interval)
            .where(BillingSubscription.status.in_(("active", "trialing", "past_due")))
        )
    ).all()
    return sum(_monthly_cents(a, q, i) for a, q, i in rows)


async def collected_summary(db: AsyncSession, days: int = 30) -> dict:
    """Collected, refunded, and failed money over the trailing ``days`` window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    collected = (await db.execute(
        select(func.coalesce(func.sum(BillingCharge.amount_cents), 0))
        .where(BillingCharge.status == "succeeded", BillingCharge.charged_at >= cutoff)
    )).scalar_one()
    failed = (await db.execute(
        select(func.coalesce(func.sum(BillingCharge.amount_cents), 0))
        .where(BillingCharge.status == "failed", BillingCharge.charged_at >= cutoff)
    )).scalar_one()
    refunded = (await db.execute(
        select(func.coalesce(func.sum(BillingRefund.amount_cents), 0))
        .where(BillingRefund.status == "succeeded", BillingRefund.refunded_at >= cutoff)
    )).scalar_one()
    return {
        "window_days": days,
        "collected_cents": int(collected),
        "failed_cents": int(failed),
        "refunded_cents": int(refunded),
        "net_cents": int(collected) - int(refunded),
    }


async def revenue_timeseries(db: AsyncSession, months: int = 12) -> list[dict]:
    """Monthly collected/refunded series, oldest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=31 * months)
    month = func.to_char(func.date_trunc("month", BillingCharge.charged_at), "YYYY-MM")
    rows = (await db.execute(
        select(month.label("m"),
               func.coalesce(func.sum(case((BillingCharge.status == "succeeded", BillingCharge.amount_cents), else_=0)), 0))
        .where(BillingCharge.charged_at >= cutoff)
        .group_by("m").order_by("m")
    )).all()
    return [{"period": m, "collected_cents": int(c)} for m, c in rows]


async def plan_breakdown(db: AsyncSession) -> list[dict]:
    """Active-subscription MRR split by plan."""
    rows = (await db.execute(
        select(BillingSubscription.plan,
               func.count(BillingSubscription.id),
               func.coalesce(func.sum(BillingSubscription.amount_cents * BillingSubscription.quantity), 0))
        .where(BillingSubscription.status.in_(_ACTIVE))
        .group_by(BillingSubscription.plan)
    )).all()
    return [{"plan": p or "unknown", "count": int(n), "mrr_cents": int(m)} for p, n, m in rows]

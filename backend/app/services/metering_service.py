"""Monthly active-lease metering for the Base subscription.

A commercial or residential lease counts once when its saved status is exactly
``Active`` for any day in the UTC billing month. The append-only monthly ledger
preserves brief Active periods and carries unchanged Active leases across month
boundaries. The first three leases are included in the $39 base fee; additional
leases are $4 each. Enterprise subscriptions bypass standard quantity sync.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billable_unit_snapshot import BillableUnitSnapshot
from app.models.billing_usage import ActiveLeaseMonth
from app.models.lease import Lease
from app.models.resident import ResidentLease

logger = logging.getLogger(__name__)

# The first three monthly-active leases are included in the $39 base fee.
INCLUDED_LEASES = 3
BILLABLE_UNIT_FLOOR = INCLUDED_LEASES
BASE_FEE_CENTS = 3900
PER_ADDITIONAL_LEASE_CENTS = 400

# Breakdown keys, in the order shown to a customer.
CATEGORIES: tuple[str, ...] = ("commercial", "residential")


# ---------------------------------------------------------------------------
# Pure helpers (no database, no clock)
# ---------------------------------------------------------------------------

def build_breakdown(
    *, commercial: int = 0, residential: int = 0
) -> dict[str, int]:
    """Assemble a per-category breakdown from raw counts.

    Negative counts are clamped to zero so a bad query result can never produce
    a total that undercharges.
    """
    return {
        "commercial": max(0, int(commercial)),
        "residential": max(0, int(residential)),
    }


def total_units(breakdown: dict[str, int]) -> int:
    """Sum a breakdown into a single billable-unit count."""
    return sum(max(0, int(breakdown.get(key, 0))) for key in CATEGORIES)


def billable_quantity(units: int, floor: int = BILLABLE_UNIT_FLOOR) -> int:
    """Quantity sent to the graduated Stripe Price."""
    return max(int(units), int(floor))


def billed_leases(units: int, included: int = INCLUDED_LEASES) -> int:
    """Return leases charged at $4 after the included allowance."""
    return max(int(units) - int(included), 0)


def estimated_monthly_charge_cents(units: int) -> int:
    return BASE_FEE_CENTS + billed_leases(units) * PER_ADDITIONAL_LEASE_CENTS


def is_billable_active_status(status: str | None) -> bool:
    return (status or "").strip().lower() in {"", "active"}


def period_month(when: datetime | None = None) -> str:
    """Return the ``YYYY-MM`` billing period for ``when`` (default: now, UTC)."""
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m")


def snapshot_payload(breakdown: dict[str, int]) -> dict:
    """Shape a breakdown plus its derived totals for storage and display."""
    units = total_units(breakdown)
    return {
        "breakdown": {key: breakdown.get(key, 0) for key in CATEGORIES},
        "billable_units": units,
        "billable_quantity": billable_quantity(units),
        "included_leases": INCLUDED_LEASES,
        "billed_leases": billed_leases(units),
        "estimated_monthly_charge_cents": estimated_monthly_charge_cents(units),
        "floor": BILLABLE_UNIT_FLOOR,
    }


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

async def record_active_lease_month(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    lease_type: str,
    lease_id: uuid.UUID,
    status: str | None,
    when: datetime | None = None,
) -> None:
    """Idempotently record a lease saved as Active in a UTC billing month."""
    if not is_billable_active_status(status):
        return
    moment = when or datetime.now(timezone.utc)
    await db.execute(
        pg_insert(ActiveLeaseMonth)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            lease_type=lease_type,
            lease_id=lease_id,
            period_month=period_month(moment),
            first_active_at=moment,
        )
        .on_conflict_do_nothing(
            constraint="uq_active_lease_month_org_lease_period"
        )
    )


async def ensure_current_active_leases(
    db: AsyncSession, org_id: uuid.UUID, *, when: datetime | None = None
) -> None:
    """Carry leases that remain Active into the current billing month."""
    moment = when or datetime.now(timezone.utc)
    commercial_ids = (
        await db.execute(
            select(Lease.id).where(
                Lease.organization_id == org_id,
                Lease.is_deleted.is_(False),
                func.lower(func.trim(func.coalesce(Lease.status, ""))).in_(("", "active")),
            )
        )
    ).scalars().all()
    residential_ids = (
        await db.execute(
            select(ResidentLease.id).where(
                ResidentLease.organization_id == org_id,
                ResidentLease.is_deleted.is_(False),
                func.lower(func.trim(func.coalesce(ResidentLease.status, ""))).in_(("", "active")),
            )
        )
    ).scalars().all()
    for lease_type, identifiers in (
        ("commercial", commercial_ids),
        ("residential", residential_ids),
    ):
        if not identifiers:
            continue
        values = [
            {
                "id": uuid.uuid4(),
                "organization_id": org_id,
                "lease_type": lease_type,
                "lease_id": lease_id,
                "period_month": period_month(moment),
                "first_active_at": moment,
            }
            for lease_id in identifiers
        ]
        await db.execute(
            pg_insert(ActiveLeaseMonth)
            .values(values)
            .on_conflict_do_nothing(
                constraint="uq_active_lease_month_org_lease_period"
            )
        )
    if commercial_ids or residential_ids:
        await db.commit()


async def count_billable_units(
    db: AsyncSession, org_id: uuid.UUID, *, period: str | None = None
) -> dict[str, int]:
    """Count distinct leases observed Active in the requested month."""
    target_period = period or period_month()
    if target_period == period_month():
        await ensure_current_active_leases(db, org_id)
    rows = (
        await db.execute(
            select(ActiveLeaseMonth.lease_type, func.count(ActiveLeaseMonth.id))
            .where(
                ActiveLeaseMonth.organization_id == org_id,
                ActiveLeaseMonth.period_month == target_period,
            )
            .group_by(ActiveLeaseMonth.lease_type)
        )
    ).all()
    counts = {lease_type: int(count) for lease_type, count in rows}
    return build_breakdown(
        commercial=counts.get("commercial", 0),
        residential=counts.get("residential", 0),
    )


async def current_billable_units(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return the org's billable-unit count right now, for display."""
    return total_units(await count_billable_units(db, org_id))


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

async def get_snapshot(
    db: AsyncSession, org_id: uuid.UUID, period: str | None = None
) -> BillableUnitSnapshot | None:
    """Return an org's snapshot for ``period`` (default: current month)."""
    result = await db.execute(
        select(BillableUnitSnapshot).where(
            BillableUnitSnapshot.organization_id == org_id,
            BillableUnitSnapshot.period_month == (period or period_month()),
        )
    )
    return result.scalar_one_or_none()


async def capture_snapshot(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    when: datetime | None = None,
    refresh: bool = False,
) -> BillableUnitSnapshot:
    """Record the org's billable units for a period, idempotently.

    A period already snapshotted is returned untouched so a re-run, a retried
    job or a second replica cannot double-count. Pass ``refresh=True`` to
    recount and update an existing period in place.
    """
    period = period_month(when)
    existing = await get_snapshot(db, org_id, period)
    if existing is not None and not refresh:
        return existing

    breakdown = await count_billable_units(db, org_id, period=period)
    units = total_units(breakdown)

    if existing is not None:
        existing.billable_units = units
        existing.breakdown = breakdown
        existing.captured_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing

    snapshot = BillableUnitSnapshot(
        organization_id=org_id,
        period_month=period,
        billable_units=units,
        breakdown=breakdown,
        captured_at=when or datetime.now(timezone.utc),
    )
    db.add(snapshot)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent writer won the unique constraint; adopt their row.
        await db.rollback()
        concurrent = await get_snapshot(db, org_id, period)
        if concurrent is None:
            raise
        return concurrent
    await db.refresh(snapshot)
    return snapshot


async def metering_summary(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Current counts plus this period's snapshot, for the billing page."""
    breakdown = await count_billable_units(db, org_id)
    payload = snapshot_payload(breakdown)
    snapshot = await get_snapshot(db, org_id)
    payload["period_month"] = period_month()
    payload["snapshot"] = (
        {
            "period_month": snapshot.period_month,
            "billable_units": snapshot.billable_units,
            "breakdown": snapshot.breakdown or {},
            "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        }
        if snapshot is not None
        else None
    )
    return payload

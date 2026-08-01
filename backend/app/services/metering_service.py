"""Billable-unit metering for per-unit (banded) subscription billing.

What counts as a billable unit
------------------------------
**One billable unit is one space the organisation is actively leasing or
managing at the moment of measurement.** Concretely, across the three primary
categories:

* **Commercial** (:class:`~app.models.lease.Lease`): each active lease in the
  portfolio. A commercial lease *is* the managed space, so the lease is the
  unit. "Active" follows :mod:`app.services.lease_limits`, the existing single
  source of truth: any lease that is not ``expired``, ``terminated`` or
  ``cancelled``, including one with no status set.
* **Residential** (:class:`~app.models.resident.RentalUnit`): each rental unit
  with at least one active org-as-lessor lease (``pending`` or ``active``).
* **Self storage** (:class:`~app.models.self_storage.StorageUnit`): each storage
  unit with at least one agreement in ``STORAGE_ACTIVE_STATUSES`` (``active``,
  ``pending_move_out``, ``delinquent``, ``in_lien``).

Three consequences of that definition, all deliberate:

* Residential and storage counts are **distinct by unit**, so two overlapping
  leases on one space (a renewal signed before the outgoing lease ends) bill
  once, not twice.
* **Vacant inventory is free.** A listed but unleased unit, and a draft or
  terminal lease, are not managed space and do not bill. Customers are charged
  for occupancy, not for cataloguing their portfolio.
* Soft-deleted rows never count.

The reported quantity is the unit count raised to :data:`BILLABLE_UNIT_FLOOR`,
matching the per-unit-with-a-floor shape competitors price on. The floor governs
only the quantity reported to Stripe; the price bands themselves live in Stripe
on a tiered/graduated price and the flat plan prices in
:mod:`app.services.entitlements` are untouched.

The plan caps (``max_offices``, ``max_active_leases``) still apply. Banding runs
alongside them until a migration off the caps is planned.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billable_unit_snapshot import BillableUnitSnapshot
from app.models.lease import Lease
from app.models.resident import ResidentLease
from app.models.self_storage import STORAGE_ACTIVE_STATUSES, StorageAgreement
from app.services.lease_limits import (
    ACTIVE_RESIDENT_STATUSES,
    INACTIVE_COMMERCIAL_STATUSES,
)

logger = logging.getLogger(__name__)

# Minimum quantity reported to the metered price. Customers below the floor pay
# the floor, which is what makes a per-unit band viable at the small end.
BILLABLE_UNIT_FLOOR = 10

# Breakdown keys, in the order shown to a customer.
CATEGORIES: tuple[str, ...] = ("commercial", "residential", "self_storage")

_ACTIVE_STORAGE_STATUSES = frozenset(s.lower() for s in STORAGE_ACTIVE_STATUSES)


# ---------------------------------------------------------------------------
# Pure helpers (no database, no clock)
# ---------------------------------------------------------------------------

def build_breakdown(
    *, commercial: int = 0, residential: int = 0, self_storage: int = 0
) -> dict[str, int]:
    """Assemble a per-category breakdown from raw counts.

    Negative counts are clamped to zero so a bad query result can never produce
    a total that undercharges.
    """
    return {
        "commercial": max(0, int(commercial)),
        "residential": max(0, int(residential)),
        "self_storage": max(0, int(self_storage)),
    }


def total_units(breakdown: dict[str, int]) -> int:
    """Sum a breakdown into a single billable-unit count."""
    return sum(max(0, int(breakdown.get(key, 0))) for key in CATEGORIES)


def billable_quantity(units: int, floor: int = BILLABLE_UNIT_FLOOR) -> int:
    """Raise a unit count to the billing floor."""
    return max(int(units), int(floor))


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
        "floor": BILLABLE_UNIT_FLOOR,
    }


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

async def _count_commercial(db: AsyncSession, org_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Lease.id)).where(
            Lease.organization_id == org_id,
            Lease.is_deleted.is_(False),
            or_(
                Lease.status.is_(None),
                func.lower(Lease.status).notin_(INACTIVE_COMMERCIAL_STATUSES),
            ),
        )
    )
    return int(result.scalar_one())


async def _count_residential(db: AsyncSession, org_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(func.distinct(ResidentLease.unit_id))).where(
            ResidentLease.organization_id == org_id,
            ResidentLease.is_deleted.is_(False),
            func.lower(ResidentLease.status).in_(ACTIVE_RESIDENT_STATUSES),
        )
    )
    return int(result.scalar_one())


async def _count_self_storage(db: AsyncSession, org_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(func.distinct(StorageAgreement.unit_id))).where(
            StorageAgreement.organization_id == org_id,
            StorageAgreement.is_deleted.is_(False),
            func.lower(StorageAgreement.status).in_(_ACTIVE_STORAGE_STATUSES),
        )
    )
    return int(result.scalar_one())


async def count_billable_units(db: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    """Return the per-category billable-unit breakdown for an org."""
    return build_breakdown(
        commercial=await _count_commercial(db, org_id),
        residential=await _count_residential(db, org_id),
        self_storage=await _count_self_storage(db, org_id),
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

    breakdown = await count_billable_units(db, org_id)
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

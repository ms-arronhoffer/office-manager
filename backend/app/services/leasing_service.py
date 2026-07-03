"""Leasing (org-as-lessor) service layer (Phase 2.1).

Holds the occupancy rules for the tenant/resident domain so the
``/api/v1/leasing`` router stays thin:

  - validating a unit has no overlapping active lease before a new tenancy
  - deriving and syncing a :class:`RentalUnit`'s occupancy status from its
    leases
  - computing unit- and property-level occupancy summaries

The organisation-as-lessor model is intentionally separate from the existing
organisation-as-lessee :class:`~app.models.lease.Lease`; nothing here touches the
office-lease tables.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.resident import (
    ACTIVE_LEASE_STATUSES,
    RentalUnit,
    ResidentLease,
)


class LeasingError(ValueError):
    """Raised for org-as-lessor leasing rule violations."""


def _overlaps(
    start_a: date | None,
    end_a: date | None,
    start_b: date | None,
    end_b: date | None,
) -> bool:
    """Return True when two (possibly open-ended) date ranges overlap.

    A ``None`` start is treated as "since forever" and a ``None`` end as
    "indefinitely", so an open-ended lease conflicts with any other lease on the
    same unit.
    """
    if start_a and end_b and start_a > end_b:
        return False
    if start_b and end_a and start_b > end_a:
        return False
    return True


async def assert_no_active_overlap(
    db: AsyncSession,
    unit_id: uuid.UUID,
    *,
    start_date: date | None,
    end_date: date | None,
    exclude_lease_id: uuid.UUID | None = None,
) -> None:
    """Ensure the unit has no other active/pending lease overlapping the term.

    Draft, ended, and terminated leases never conflict, so several drafts can be
    prepared for the same unit; only when a lease becomes ``pending``/``active``
    is exclusivity enforced.
    """
    stmt = (
        select(ResidentLease)
        .where(
            ResidentLease.unit_id == unit_id,
            ResidentLease.is_deleted.is_(False),
            ResidentLease.status.in_(ACTIVE_LEASE_STATUSES),
        )
    )
    if exclude_lease_id is not None:
        stmt = stmt.where(ResidentLease.id != exclude_lease_id)
    existing = (await db.execute(stmt)).scalars().all()
    for lease in existing:
        if _overlaps(start_date, end_date, lease.start_date, lease.end_date):
            raise LeasingError(
                "This unit already has an active or pending lease overlapping "
                "the requested term."
            )


def unit_status_from_leases(unit: RentalUnit) -> str:
    """Derive occupancy status from a unit's leases, preserving manual holds.

    A unit explicitly marked ``unavailable`` (e.g. down for renovation) keeps
    that status regardless of leases. Otherwise the unit is ``occupied`` when it
    has any active/pending lease and ``available`` when it does not.
    """
    if unit.status == "unavailable":
        return "unavailable"
    for lease in unit.leases:
        if getattr(lease, "is_deleted", False):
            continue
        if lease.status in ACTIVE_LEASE_STATUSES:
            return "occupied"
    return "available"


async def sync_unit_status(
    db: AsyncSession,
    unit_id: uuid.UUID,
    organization_id: uuid.UUID | None,
) -> RentalUnit | None:
    """Recompute and persist a unit's occupancy status from its leases."""
    unit = (
        await db.execute(
            select(RentalUnit)
            .where(
                RentalUnit.id == unit_id,
                RentalUnit.organization_id == organization_id,
            )
            .options(selectinload(RentalUnit.leases))
        )
    ).scalar_one_or_none()
    if unit is None:
        return None
    new_status = unit_status_from_leases(unit)
    if unit.status != new_status:
        unit.status = new_status
    return unit


async def occupancy_summary(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    office_id: uuid.UUID | None = None,
) -> dict:
    """Build a portfolio occupancy summary over non-deleted units.

    Returns unit counts by status plus a physical-occupancy rate (occupied /
    (available + occupied)); manually ``unavailable`` units are excluded from the
    rate denominator since they are not rentable.
    """
    stmt = (
        select(RentalUnit)
        .where(
            RentalUnit.organization_id == organization_id,
            RentalUnit.is_deleted.is_(False),
        )
        .options(selectinload(RentalUnit.leases))
    )
    if office_id is not None:
        stmt = stmt.where(RentalUnit.office_id == office_id)
    units = (await db.execute(stmt)).scalars().unique().all()

    counts = {"available": 0, "occupied": 0, "unavailable": 0}
    for unit in units:
        status = unit_status_from_leases(unit)
        counts[status] = counts.get(status, 0) + 1

    rentable = counts["available"] + counts["occupied"]
    rate = round(counts["occupied"] / rentable, 4) if rentable else 0.0
    return {
        "total_units": len(units),
        "counts": counts,
        "occupancy_rate": rate,
    }

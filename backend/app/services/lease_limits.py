"""Active-lease tier limit: classification, counting, and enforcement.

Both the commercial portfolio (:class:`app.models.lease.Lease`) and the
residential leasing funnel (:class:`app.models.resident.ResidentLease`) count
toward a single org-wide "active leases" cap defined by the plan entitlements
(``max_active_leases`` — Starter 100, Pro 500, Enterprise unlimited).

This module is the single source of truth for what counts as an *active* lease
and for the org-scoped count used to enforce the cap when a lease is created.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease
from app.models.organization import Organization
from app.models.resident import ResidentLease
from app.services import entitlements as ent

# Entitlement limit key for the active-lease cap.
LEASE_LIMIT_KEY = "max_active_leases"

# Commercial lease statuses that do NOT count as active (terminal / closed).
# A commercial lease with no status is treated as active (a live record).
INACTIVE_COMMERCIAL_STATUSES: frozenset[str] = frozenset(
    {"expired", "terminated", "cancelled"}
)

# Residential lease statuses that DO count as active (draft/ended/terminated do
# not consume a slot).
ACTIVE_RESIDENT_STATUSES: frozenset[str] = frozenset({"pending", "active"})


def _normalize(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def is_active_commercial_status(status_value: object) -> bool:
    """Return whether a commercial lease status counts toward the active cap."""
    return _normalize(status_value) not in INACTIVE_COMMERCIAL_STATUSES


def is_active_resident_status(status_value: object) -> bool:
    """Return whether a residential lease status counts toward the active cap."""
    return _normalize(status_value) in ACTIVE_RESIDENT_STATUSES


async def count_active_leases(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return the number of active leases (commercial + residential) for an org."""
    commercial = (
        await db.execute(
            select(func.count(Lease.id)).where(
                Lease.organization_id == org_id,
                Lease.is_deleted.is_(False),
                or_(
                    Lease.status.is_(None),
                    func.lower(Lease.status).notin_(INACTIVE_COMMERCIAL_STATUSES),
                ),
            )
        )
    ).scalar_one()
    residential = (
        await db.execute(
            select(func.count(ResidentLease.id)).where(
                ResidentLease.organization_id == org_id,
                ResidentLease.is_deleted.is_(False),
                func.lower(ResidentLease.status).in_(ACTIVE_RESIDENT_STATUSES),
            )
        )
    ).scalar_one()
    return int(commercial) + int(residential)


async def enforce_active_lease_limit(
    db: AsyncSession, org: Organization | None
) -> None:
    """Raise HTTP 402 when creating another active lease would exceed the cap.

    ``org`` may be ``None`` (no organization context) in which case no limit is
    enforced. Unlimited plans (``None`` limit) never block.
    """
    if org is None:
        return
    limit = ent.get_limit(org, LEASE_LIMIT_KEY)
    if limit is None:
        return
    current = await count_active_leases(db, org.id)
    if current >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Active lease limit reached for the {org.plan} plan "
                f"(max {limit}). Please upgrade your plan to add more active leases."
            ),
        )

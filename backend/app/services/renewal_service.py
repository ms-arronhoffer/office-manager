"""Turning lease deadlines into work that someone owns.

A dashboard count of "overdue notices" does not stop a renewal being missed;
somebody has to be told, by name, that an action is due. This service:

* derives the date by which notice must be served for a lease,
* opens a renewal record automatically as that date approaches, assigning it to
  the lease's manager so it lands in a person's queue rather than a statistic,
* records notice delivery with a method and reference that can be produced as
  evidence later,
* and exposes the renewal/option pipeline as an exception queue sorted by
  urgency.

The scheduled entry point is :func:`open_due_renewals`, run daily by
:mod:`app.tasks.renewal_deadlines`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease
from app.models.lease_option import LeaseOption
from app.models.lease_renewal import LeaseRenewal
from app.models.office import Manager
from app.models.user import User

# How far ahead of the notice deadline a renewal should be opened. Renewal
# negotiations routinely take a quarter, so the work starts well before the
# date the notice legally has to be served.
DEFAULT_LEAD_DAYS = 120

# Renewal states that still need attention.
OPEN_RENEWAL_STATUSES = ("in_progress", "pending")

# Escalation bands, in days remaining until the notice deadline.
URGENCY_BANDS = (
    ("overdue", -10_000, -1),
    ("critical", 0, 14),
    ("urgent", 15, 45),
    ("upcoming", 46, 10_000),
)


def notice_due_date(lease: Lease) -> date | None:
    """The last date notice can be served for a lease.

    Prefers an explicitly recorded notice date, otherwise derives it by backing
    the notice period off the expiration date.
    """
    if lease.lease_notice_date:
        return lease.lease_notice_date
    if lease.lease_expiration and lease.notice_period_days:
        return lease.lease_expiration - timedelta(days=int(lease.notice_period_days))
    return None


def days_remaining(due: date | None, today: date | None = None) -> int | None:
    """Days until ``due``; negative once the date has passed."""
    if due is None:
        return None
    return (due - (today or date.today())).days


def urgency(days: int | None) -> str:
    """Bucket a countdown into an escalation band."""
    if days is None:
        return "unscheduled"
    for label, low, high in URGENCY_BANDS:
        if low <= days <= high:
            return label
    return "upcoming"


async def _manager_user_id(db: AsyncSession, lease: Lease) -> uuid.UUID | None:
    """Best-effort mapping from a lease's manager to an application user.

    Managers are directory records rather than logins, so the link is made on
    email address. An unmatched manager simply leaves the renewal unassigned
    for a human to pick up, which the pipeline surfaces as an exception.
    """
    if lease.manager_id is None:
        return None
    manager = await db.get(Manager, lease.manager_id)
    if manager is None or not manager.email:
        return None
    return (
        await db.execute(
            select(User.id).where(
                User.email == manager.email,
                User.organization_id == lease.organization_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def open_due_renewals(
    db: AsyncSession,
    *,
    today: date | None = None,
    lead_days: int = DEFAULT_LEAD_DAYS,
) -> list[LeaseRenewal]:
    """Open renewal records for leases whose notice deadline is approaching.

    Idempotent: a lease that already has an open renewal is skipped, so the job
    can run daily without creating duplicates.
    """
    today = today or date.today()
    horizon = today + timedelta(days=lead_days)

    leases = (
        (
            await db.execute(
                select(Lease).where(
                    Lease.is_deleted.is_(False),
                    Lease.lease_expiration.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )

    existing = {
        renewal.lease_id
        for renewal in (
            await db.execute(
                select(LeaseRenewal).where(
                    LeaseRenewal.status.in_(OPEN_RENEWAL_STATUSES)
                )
            )
        )
        .scalars()
        .all()
    }

    created: list[LeaseRenewal] = []
    for lease in leases:
        if lease.id in existing:
            continue
        due = notice_due_date(lease)
        if due is None or due > horizon:
            continue
        renewal = LeaseRenewal(
            lease_id=lease.id,
            status="in_progress",
            target_expiration=lease.lease_expiration,
            notice_due_date=due,
            owner_id=await _manager_user_id(db, lease),
            auto_opened=True,
            notes=(
                f"Opened automatically: notice for {lease.lease_name} is due {due}."
            ),
        )
        db.add(renewal)
        created.append(renewal)

    if created:
        await db.commit()
    return created


def record_notice(
    renewal: LeaseRenewal,
    *,
    method: str | None = None,
    reference: str | None = None,
) -> None:
    """Mark notice as served, capturing how it was delivered."""
    renewal.notice_sent_at = datetime.now(timezone.utc)
    renewal.notice_method = method
    renewal.notice_reference = reference


def exercise_option(
    option: LeaseOption,
    *,
    user_id: uuid.UUID | None,
    lease_id: uuid.UUID,
) -> LeaseRenewal:
    """Exercise an option and produce the renewal it commits the business to."""
    if option.status != "open":
        raise ValueError(f"Option is {option.status} and can no longer be exercised.")

    renewal = LeaseRenewal(
        lease_id=lease_id,
        status="in_progress",
        new_rent_amount=option.new_rent_amount,
        owner_id=user_id,
        created_by_id=user_id,
        notes=f"Created by exercising the {option.option_type} option.",
    )
    option.status = "exercised"
    option.exercised_at = datetime.now(timezone.utc)
    option.exercised_by_id = user_id
    return renewal


def pipeline_entry(lease: Lease, renewal: LeaseRenewal | None, today: date | None = None) -> dict:
    """Shape a lease + renewal pair as a work-queue row."""
    due = renewal.notice_due_date if renewal and renewal.notice_due_date else notice_due_date(lease)
    remaining = days_remaining(due, today)
    if renewal is None:
        stage = "not_started"
    elif renewal.executed_at:
        stage = "executed"
    elif renewal.terms_agreed_at:
        stage = "terms_agreed"
    elif renewal.notice_sent_at:
        stage = "notice_served"
    else:
        stage = "open"
    return {
        "lease_id": lease.id,
        "lease_name": lease.lease_name,
        "office_id": lease.office_id,
        "lease_expiration": lease.lease_expiration,
        "notice_due_date": due,
        "days_until_notice_due": remaining,
        "urgency": urgency(remaining),
        "renewal_id": renewal.id if renewal else None,
        "renewal_status": renewal.status if renewal else None,
        "stage": stage,
        "owner_id": renewal.owner_id if renewal else None,
        "notice_sent_at": renewal.notice_sent_at if renewal else None,
    }

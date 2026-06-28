"""Preventive-maintenance automation engine.

Turns recurring :class:`~app.models.maintenance.MaintenanceTask` records into
actionable work orders. A task opted into automation
(``auto_generate_work_order``) spawns a :class:`~app.models.maintenance_ticket.MaintenanceTicket`
``work_order_lead_days`` ahead of its ``next_due_date``. The originating task is
recorded on the ticket (``source_task_id``) and on the task itself
(``last_generated_due_date``) so each due cycle produces at most one work order.

The same generation primitive backs both the nightly scheduler job and the
on-demand "generate work order now" endpoint.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintenanceTask
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.user import User

logger = logging.getLogger(__name__)

# Name of the auto-managed ticket category PM work orders are filed under.
PM_CATEGORY_NAME = "Preventive Maintenance"


def task_is_due_for_generation(task: MaintenanceTask, today: date | None = None) -> bool:
    """Return whether *task* should spawn a work order as of *today*.

    A task qualifies when automation is enabled, it has a due date, it is not
    already completed, the due date is within the configured lead window, and a
    work order has not already been generated for this due cycle.
    """
    today = today or date.today()
    if not task.auto_generate_work_order:
        return False
    if task.next_due_date is None:
        return False
    if task.status == "completed":
        return False
    if task.last_generated_due_date == task.next_due_date:
        return False
    lead = task.work_order_lead_days or 0
    generate_on = task.next_due_date - _days(lead)
    return today >= generate_on


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


async def get_or_create_pm_category(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> TicketCategory:
    """Return the org's auto-managed Preventive Maintenance category, creating it
    if necessary. Category names are unique per organization."""
    existing = (
        await db.execute(
            select(TicketCategory).where(
                TicketCategory.organization_id == organization_id,
                TicketCategory.name == PM_CATEGORY_NAME,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    category = TicketCategory(name=PM_CATEGORY_NAME, organization_id=organization_id)
    db.add(category)
    await db.flush()
    return category


async def _pick_creator_id(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Pick a stable system creator for auto-generated work orders.

    Prefers the longest-standing admin, then any admin/editor in the org. The
    ticket's ``created_by_id`` is a required FK, so generation is skipped when no
    suitable user exists.
    """
    result = await db.execute(
        select(User.id)
        .where(
            User.organization_id == organization_id,
            User.role.in_(("admin", "editor")),
            User.is_active.is_(True),
        )
        .order_by(User.role != "admin", User.created_at.asc())
        .limit(1)
    )
    return result.scalars().first()


def _priority_for(task: MaintenanceTask) -> str:
    """Regulatory PM is high priority; everything else is medium."""
    return "high" if task.is_regulatory else "medium"


async def generate_work_order_for_task(
    db: AsyncSession,
    task: MaintenanceTask,
    *,
    created_by_id: uuid.UUID | None = None,
    today: date | None = None,
) -> MaintenanceTicket | None:
    """Create a single work-order ticket for *task* and mark its due cycle.

    Returns the created ticket, or ``None`` when generation is skipped because a
    required field (office or a creator user) is missing. The caller owns the
    surrounding transaction (``flush`` is used, not ``commit``).
    """
    today = today or date.today()

    if task.office_id is None:
        logger.warning(
            "PM task %s (%s) has no office — skipping work-order generation",
            task.id,
            task.title,
        )
        return None

    creator_id = created_by_id or await _pick_creator_id(db, task.organization_id)
    if creator_id is None:
        logger.warning(
            "No admin/editor user for org %s — skipping PM work order for task %s",
            task.organization_id,
            task.id,
        )
        return None

    category = await get_or_create_pm_category(db, task.organization_id)

    due_label = task.next_due_date.isoformat() if task.next_due_date else "unscheduled"
    description = task.description or (
        f"Auto-generated preventive-maintenance work order for \"{task.title}\" "
        f"(due {due_label})."
    )

    ticket = MaintenanceTicket(
        organization_id=task.organization_id,
        subject=f"PM: {task.title}"[:255],
        description=description,
        priority=_priority_for(task),
        status="open",
        category_id=category.id,
        office_id=task.office_id,
        vendor_id=task.vendor_id,
        created_by_id=creator_id,
        source_task_id=task.id,
        scheduled_date=None,
    )
    db.add(ticket)

    # Mark this due cycle as generated so it is not produced again.
    task.last_generated_due_date = task.next_due_date

    logger.info(
        "Generated PM work order for task %s (%s), due %s",
        task.id,
        task.title,
        due_label,
    )
    return ticket


async def generate_due_work_orders(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None = None,
    today: date | None = None,
) -> list[MaintenanceTicket]:
    """Generate work orders for every due, automation-enabled task.

    When *organization_id* is given, only that org's tasks are considered. The
    caller owns the transaction; this function flushes but does not commit.
    """
    today = today or date.today()

    query = select(MaintenanceTask).where(
        MaintenanceTask.auto_generate_work_order.is_(True),
        MaintenanceTask.next_due_date.is_not(None),
        MaintenanceTask.status != "completed",
    )
    if organization_id is not None:
        query = query.where(MaintenanceTask.organization_id == organization_id)

    tasks = (await db.execute(query)).scalars().all()

    created: list[MaintenanceTicket] = []
    for task in tasks:
        if not task_is_due_for_generation(task, today):
            continue
        ticket = await generate_work_order_for_task(db, task, today=today)
        if ticket is not None:
            created.append(ticket)
    return created

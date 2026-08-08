"""APScheduler task: open renewals and escalate transition work before it slips.

Two deadline-driven jobs run here:

* :func:`open_renewal_deadlines` opens a renewal record, owned by a named
  person, for every lease whose notice date is inside the lead window.
* :func:`escalate_overdue_transition_tasks` notifies the assignee of any
  transition checklist item that is past its due date, rate-limited so an owner
  is reminded at most once a day.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.notification import Notification
from app.models.transition import OfficeTransition, TransitionChecklistItem
from app.services.renewal_service import open_due_renewals

logger = logging.getLogger(__name__)

# Do not re-notify the same owner about the same item more than once a day.
REMINDER_INTERVAL_HOURS = 24


async def open_renewal_deadlines() -> None:
    async with async_session() as db:
        try:
            created = await open_due_renewals(db)
        except Exception:
            logger.exception("Renewal deadline scan failed")
            await db.rollback()
            return
        logger.info("[RENEWAL DEADLINES] Opened %d renewal(s)", len(created))


async def escalate_overdue_transition_tasks() -> None:
    async with async_session() as db:
        try:
            count = await _notify_overdue_items(db)
        except Exception:
            logger.exception("Transition escalation failed")
            await db.rollback()
            return
        logger.info("[TRANSITION ESCALATION] Notified %d overdue task(s)", count)


async def _notify_overdue_items(db: AsyncSession, today: date | None = None) -> int:
    today = today or date.today()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=REMINDER_INTERVAL_HOURS)

    items = (
        (
            await db.execute(
                select(TransitionChecklistItem, OfficeTransition)
                .join(
                    OfficeTransition,
                    OfficeTransition.id == TransitionChecklistItem.transition_id,
                )
                .where(
                    TransitionChecklistItem.is_complete.is_(False),
                    TransitionChecklistItem.due_date.isnot(None),
                    TransitionChecklistItem.due_date < today,
                    TransitionChecklistItem.assigned_to_id.isnot(None),
                    OfficeTransition.is_deleted.is_(False),
                    OfficeTransition.status != "complete",
                )
            )
        )
        .all()
    )

    notified = 0
    for item, transition in items:
        if item.last_reminded_at and item.last_reminded_at > cutoff:
            continue
        overdue_days = (today - item.due_date).days
        db.add(
            Notification(
                organization_id=transition.organization_id,
                user_id=item.assigned_to_id,
                kind="transition_task_overdue",
                title="Overdue transition task",
                body=(
                    f'"{item.item_label}" was due {item.due_date.isoformat()} '
                    f"({overdue_days} day(s) overdue)."
                ),
                entity_type="transition",
                entity_id=transition.id,
            )
        )
        item.last_reminded_at = datetime.now(timezone.utc)
        notified += 1

    if notified:
        await db.commit()
    return notified

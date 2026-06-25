"""APScheduler task: auto-create maintenance tickets for active recurring rules."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.models.recurring_ticket_rule import RecurringTicketRule
from app.models.maintenance_ticket import MaintenanceTicket

logger = logging.getLogger(__name__)


def _compute_next_run(frequency: str, day_of_week, day_of_month) -> datetime:
    """Recompute next_run_at after a rule fires."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    base = now.replace(hour=8, minute=0, second=0, microsecond=0)

    if frequency == "daily":
        return base + timedelta(days=1)

    if frequency == "weekly":
        if day_of_week is None:
            day_of_week = 0
        days_ahead = (day_of_week - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return base + timedelta(days=days_ahead)

    if frequency == "monthly":
        if day_of_month is None:
            day_of_month = 1
        import calendar
        # Next month
        if base.month == 12:
            next_month = base.replace(year=base.year + 1, month=1)
        else:
            next_month = base.replace(month=base.month + 1)
        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
        day = min(day_of_month, last_day)
        return next_month.replace(day=day)

    return base + timedelta(days=1)


async def create_recurring_tickets() -> None:
    """Query active rules due to run and create a MaintenanceTicket for each."""
    now = datetime.now(timezone.utc)
    logger.info("Running recurring ticket task at %s", now.isoformat())

    async with async_session() as db:
        try:
            result = await db.execute(
                select(RecurringTicketRule)
                .options(
                    joinedload(RecurringTicketRule.category),
                    joinedload(RecurringTicketRule.office),
                    joinedload(RecurringTicketRule.assigned_to),
                )
                .where(
                    RecurringTicketRule.is_active.is_(True),
                    RecurringTicketRule.next_run_at <= now,
                )
            )
            rules = result.scalars().unique().all()
        except Exception:
            logger.exception("Failed to query recurring ticket rules")
            return

        if not rules:
            logger.info("No recurring rules due — skipping")
            return

        for rule in rules:
            try:
                # Validate required FK fields exist
                if not rule.category_id or not rule.office_id:
                    logger.warning(
                        "Recurring rule %s (%s) missing category_id or office_id — skipping",
                        rule.id,
                        rule.name,
                    )
                    rule.next_run_at = _compute_next_run(rule.frequency, rule.day_of_week, rule.day_of_month)
                    continue

                ticket = MaintenanceTicket(
                    subject=rule.subject,
                    description=rule.description or "",
                    priority=rule.priority,
                    status="open",
                    category_id=rule.category_id,
                    office_id=rule.office_id,
                    assigned_to_id=rule.assigned_to_id,
                    created_by_id=rule.created_by_id,
                )
                db.add(ticket)

                rule.last_run_at = now
                rule.next_run_at = _compute_next_run(rule.frequency, rule.day_of_week, rule.day_of_month)

                logger.info(
                    "Created recurring ticket for rule %s (%s), next run: %s",
                    rule.id,
                    rule.name,
                    rule.next_run_at.isoformat(),
                )
            except Exception:
                logger.exception("Failed to process recurring rule %s", rule.id)

        try:
            await db.commit()
        except Exception:
            logger.exception("Failed to commit recurring tickets")
            await db.rollback()

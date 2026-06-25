"""APScheduler task: auto-escalate maintenance tickets that have exceeded their SLA threshold."""

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.models.maintenance_ticket import MaintenanceTicket, TicketNote
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services.webhook_service import dispatch_webhook
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

_DEFAULT_SLA_DAYS = {"high": 1, "medium": 3, "low": 7}
_PRIORITY_BUMP = {"low": "medium", "medium": "high", "high": "high"}


async def _get_sla_days(db) -> dict[str, int]:
    res = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
    row = res.scalar_one_or_none()
    if row is None:
        return _DEFAULT_SLA_DAYS.copy()
    return {
        "high": row.sla_high_days if row.sla_high_days is not None else _DEFAULT_SLA_DAYS["high"],
        "medium": row.sla_medium_days if row.sla_medium_days is not None else _DEFAULT_SLA_DAYS["medium"],
        "low": row.sla_low_days if row.sla_low_days is not None else _DEFAULT_SLA_DAYS["low"],
    }


async def check_sla_breaches() -> None:
    """Run daily at 8:30 AM. Escalate open/in_progress tickets past their SLA threshold."""
    now = datetime.now(timezone.utc)
    logger.info("Running SLA escalation check at %s", now.isoformat())

    async with async_session() as db:
        try:
            sla_days = await _get_sla_days(db)
        except Exception:
            logger.exception("Failed to load SLA thresholds")
            return

        # Build per-priority cutoff datetimes
        cutoffs = {
            priority: now - timedelta(days=days)
            for priority, days in sla_days.items()
        }

        # Query breaching tickets with relationships needed for email/note
        try:
            result = await db.execute(
                select(MaintenanceTicket)
                .options(
                    joinedload(MaintenanceTicket.office),
                    joinedload(MaintenanceTicket.category),
                    joinedload(MaintenanceTicket.created_by),
                    joinedload(MaintenanceTicket.assigned_to),
                )
                .where(
                    MaintenanceTicket.is_deleted.is_(False),
                    MaintenanceTicket.status.in_(["open", "in_progress"]),
                )
            )
            tickets = result.scalars().unique().all()
        except Exception:
            logger.exception("Failed to query tickets for SLA escalation")
            return

        breaching = [
            t for t in tickets
            if t.priority in cutoffs and t.created_at is not None
            and (
                t.created_at.replace(tzinfo=timezone.utc)
                if t.created_at.tzinfo is None else t.created_at
            ) < cutoffs[t.priority]
        ]

        if not breaching:
            logger.info("No SLA breaches found — skipping")
            return

        logger.info("Found %d SLA-breaching tickets", len(breaching))

        # Build per-org admin ID map to avoid N+1 queries
        org_ids = {t.organization_id for t in breaching if t.organization_id is not None}
        org_admin_ids: dict = {}
        for org_id in org_ids:
            try:
                admin_result = await db.execute(
                    select(User.id).where(
                        User.role == "admin",
                        User.is_active.is_(True),
                        User.organization_id == org_id,
                    )
                )
                org_admin_ids[org_id] = [row[0] for row in admin_result.all()]
            except Exception:
                logger.exception("Failed to query admin users for org %s", org_id)
                org_admin_ids[org_id] = []

        # Track old→new priority for post-commit use (ticket object mutated before commit)
        priority_changes: dict = {}

        for ticket in breaching:
            old_priority = ticket.priority
            new_priority = _PRIORITY_BUMP.get(old_priority, old_priority)
            priority_changes[ticket.id] = (old_priority, new_priority)

            if new_priority != old_priority:
                ticket.priority = new_priority
                note_text = (
                    f"System: SLA threshold exceeded ({sla_days[old_priority]} day(s) for "
                    f"{old_priority} priority). Priority escalated from {old_priority} to {new_priority}."
                )
            else:
                note_text = (
                    f"System: SLA threshold exceeded ({sla_days[old_priority]} day(s) for "
                    f"{old_priority} priority). Ticket remains at high priority."
                )

            # Get next note_order
            try:
                order_result = await db.execute(
                    select(func.coalesce(func.max(TicketNote.note_order), 0))
                    .where(TicketNote.ticket_id == ticket.id)
                )
                next_order = order_result.scalar_one() + 1
            except Exception:
                next_order = 1

            note = TicketNote(
                ticket_id=ticket.id,
                note_text=note_text,
                note_order=next_order,
                created_by_id=None,
            )
            db.add(note)

        try:
            await db.commit()
            logger.info("Committed priority escalations for %d tickets", len(breaching))
        except Exception:
            logger.exception("Failed to commit SLA escalations")
            await db.rollback()
            return

        # Post-commit: send emails, notifications, and webhooks (best-effort)
        # Group tickets by org for webhook dispatch
        tickets_by_org: dict = defaultdict(list)
        for ticket in breaching:
            if ticket.organization_id is not None:
                tickets_by_org[ticket.organization_id].append(ticket)

        for ticket in breaching:
            old_priority, new_priority = priority_changes[ticket.id]

            # Send high-priority email if ticket is now (or was already) high
            if new_priority == "high":
                try:
                    from app.tasks.ticket_email import send_high_priority_ticket_emails
                    await send_high_priority_ticket_emails(db, ticket)
                except Exception:
                    logger.exception("SLA escalation email failed for ticket %s", ticket.id)

            # Notify admins scoped to this ticket's org
            admin_ids = org_admin_ids.get(ticket.organization_id, [])
            for admin_id in admin_ids:
                try:
                    body = (
                        f"Priority escalated from {old_priority} to {new_priority}."
                        if old_priority != new_priority
                        else f"Ticket remains at {old_priority} priority (threshold exceeded)."
                    )
                    await create_notification(
                        db,
                        user_id=admin_id,
                        kind="sla_breach",
                        title=f"SLA breach: {ticket.subject}",
                        body=body,
                        entity_type="ticket",
                        entity_id=ticket.id,
                    )
                except Exception:
                    logger.exception("Failed to create SLA notification for admin %s", admin_id)

        # Dispatch sla.breached webhook once per org
        for org_id, org_tickets in tickets_by_org.items():
            try:
                await dispatch_webhook(
                    db,
                    org_id,
                    "sla.breached",
                    {
                        "breached_count": len(org_tickets),
                        "tickets": [
                            {
                                "ticket_id": str(t.id),
                                "subject": t.subject,
                                "priority": t.priority,
                                "old_priority": priority_changes[t.id][0],
                            }
                            for t in org_tickets
                        ],
                    },
                )
            except Exception:
                logger.exception("Failed to dispatch sla.breached webhook for org %s", org_id)


"""Weekly summary email sent every Monday morning."""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EmailReminderRule, EmailLog
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket
from app.utils.email_client import send_email

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
template_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))


async def send_weekly_summary() -> None:
    """Aggregate stats and email all weekly_summary rule recipients."""
    async for db in get_db():
        await _run(db)
        break


async def _run(db: AsyncSession) -> None:
    try:
        result = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type == "weekly_summary",
                EmailReminderRule.is_active == True,  # noqa: E712
            )
        )
        rules = result.scalars().all()
    except Exception:
        logger.exception("Failed to load weekly_summary rules")
        return

    if not rules:
        logger.info("No active weekly_summary rules — skipping")
        return

    # --- Stats ---
    today = date.today()
    cutoff_30 = today + timedelta(days=30)
    overdue_cutoff = datetime.now() - timedelta(days=7)

    open_count_result = await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.status.in_(["open", "in_progress"]),
            MaintenanceTicket.is_deleted.is_(False),
        )
    )
    open_tickets = open_count_result.scalar_one()

    overdue_result = await db.execute(
        select(MaintenanceTicket).where(
            MaintenanceTicket.status.in_(["open", "in_progress"]),
            MaintenanceTicket.created_at < overdue_cutoff,
            MaintenanceTicket.is_deleted.is_(False),
        ).order_by(MaintenanceTicket.created_at.asc()).limit(10)
    )
    overdue_tickets_list = overdue_result.scalars().all()

    expiring_result = await db.execute(
        select(Lease).where(
            Lease.lease_expiration != None,  # noqa: E711
            Lease.lease_expiration <= cutoff_30,
            Lease.lease_expiration >= today,
            Lease.is_deleted.is_(False),
        ).order_by(Lease.lease_expiration.asc()).limit(10)
    )
    expiring_leases = expiring_result.scalars().all()

    try:
        template = template_env.get_template("weekly_summary.html")
    except Exception:
        logger.exception("Failed to load weekly_summary.html template")
        return

    week_of = today.strftime("%B %d, %Y")
    context = {
        "week_of": week_of,
        "open_tickets": open_tickets,
        "overdue_tickets": len(overdue_tickets_list),
        "leases_expiring_30": len(expiring_leases),
        "expiring_leases": [
            {"name": l.lease_name, "expires": l.lease_expiration.isoformat() if l.lease_expiration else ""}
            for l in expiring_leases
        ],
        "overdue_ticket_list": [
            {
                "subject": t.subject,
                "days_open": (datetime.now() - t.created_at).days if t.created_at else "?",
            }
            for t in overdue_tickets_list
        ],
    }

    for rule in rules:
        for recipient in rule.recipient_emails or []:
            try:
                html = template.render(**context)
                email_subject = f"Weekly Office Summary — {week_of}"
                sent = await send_email(recipient, email_subject, html)
                log = EmailLog(
                    rule_id=rule.id,
                    sent_to=recipient,
                    subject=email_subject,
                    body=html,
                    status="sent" if sent else "failed",
                )
                db.add(log)
            except Exception:
                logger.exception("Failed to send weekly_summary to %s", recipient)

    try:
        await db.commit()
    except Exception:
        logger.exception("Failed to commit weekly_summary EmailLog rows")
        await db.rollback()

    logger.info("Weekly summary sent for week of %s", week_of)

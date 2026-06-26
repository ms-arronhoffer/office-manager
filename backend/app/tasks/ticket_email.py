"""Send immediate email notifications when a high-priority ticket is created."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Environment, FileSystemLoader

from app.models import EmailReminderRule, EmailLog
from app.models.maintenance_ticket import MaintenanceTicket
from app.utils.email_client import send_email

logger = logging.getLogger(__name__)

# Absolute path so the loader doesn't depend on the process working directory.
_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
template_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))


async def send_high_priority_ticket_emails(db: AsyncSession, ticket: MaintenanceTicket) -> None:
    """Query active high_priority_ticket rules and send emails immediately.

    Failures in template rendering, SMTP, or EmailLog inserts are logged
    but never propagated — the ticket creation has already succeeded by
    the time this is called.
    """
    try:
        result = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type == "high_priority_ticket",
                EmailReminderRule.is_active == True,  # noqa: E712
            )
        )
        rules = result.scalars().all()
    except Exception:
        logger.exception("Failed to load high-priority email rules")
        return

    if not rules:
        return

    try:
        template = template_env.get_template("high_priority_ticket.html")
    except Exception:
        logger.exception("Failed to load high_priority_ticket.html template")
        return

    office_name = ticket.office.location_name if ticket.office else "N/A"
    created_by_name = ticket.created_by.display_name if ticket.created_by else "N/A"
    category_name = ticket.category.name if ticket.category else "N/A"

    sent_count = 0
    for rule in rules:
        for recipient in rule.recipient_emails or []:
            try:
                html = template.render(
                    subject=ticket.subject,
                    office_name=office_name,
                    category=category_name,
                    description=ticket.description,
                    created_by=created_by_name,
                    created_at=ticket.created_at.strftime("%Y-%m-%d %H:%M") if ticket.created_at else "N/A",
                    location_hours=ticket.location_hours or "N/A",
                )
                email_subject = f"[HIGH PRIORITY] {ticket.subject} - {office_name}"
                sent = await send_email(recipient, email_subject, html)

                log = EmailLog(
                    rule_id=rule.id,
                    sent_to=recipient,
                    subject=email_subject,
                    body=html,
                    status="sent" if sent else "failed",
                )
                db.add(log)
                if sent:
                    sent_count += 1
            except Exception:
                logger.exception(
                    "Failed to render or send high-priority email to %s for ticket %s",
                    recipient,
                    ticket.id,
                )

    try:
        await db.commit()
    except Exception:
        logger.exception("Failed to commit EmailLog rows for ticket %s", ticket.id)
        await db.rollback()
        return

    logger.info(
        "High-priority ticket %s: queued/sent %d notifications",
        ticket.id,
        sent_count,
    )


async def send_ticket_created_emails(db: AsyncSession, ticket: MaintenanceTicket) -> None:
    """Notify the office manager and the assigned vendor that a ticket was created.

    Sends to the office's manager email (if configured) and the assigned
    vendor's contact email (if a vendor is assigned and has an email). All
    failures are logged but never propagated — ticket creation has already
    succeeded by the time this is called.
    """
    recipients: list[str] = []

    manager = ticket.office.manager if ticket.office else None
    if manager and manager.email:
        recipients.append(manager.email)

    vendor = ticket.vendor
    vendor_name = vendor.company_name if vendor else None
    if vendor and vendor.contact_email and vendor.contact_email not in recipients:
        recipients.append(vendor.contact_email)

    if not recipients:
        return

    try:
        template = template_env.get_template("ticket_created.html")
    except Exception:
        logger.exception("Failed to load ticket_created.html template")
        return

    office_name = ticket.office.location_name if ticket.office else "N/A"
    created_by_name = ticket.created_by.display_name if ticket.created_by else "N/A"
    category_name = ticket.category.name if ticket.category else "N/A"

    for recipient in recipients:
        try:
            html = template.render(
                subject=ticket.subject,
                office_name=office_name,
                category=category_name,
                priority=ticket.priority.title() if ticket.priority else "N/A",
                status=ticket.status.replace("_", " ").title() if ticket.status else "N/A",
                description=ticket.description or "",
                created_by=created_by_name,
                location_hours=ticket.location_hours or "",
                vendor_name=vendor_name,
            )
            email_subject = f"New Maintenance Ticket: {ticket.subject} - {office_name}"
            await send_email(recipient, email_subject, html)
        except Exception:
            logger.exception(
                "Failed to send ticket_created email to %s for ticket %s",
                recipient,
                ticket.id,
            )


async def send_ticket_status_email(
    db: AsyncSession,
    ticket: MaintenanceTicket,
    old_status: str,
    new_status: str,
    updated_by_name: str,
) -> None:
    """Send status-change notification to admin/editor rules of type ticket_status_change."""
    try:
        result = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type == "ticket_status_change",
                EmailReminderRule.is_active == True,  # noqa: E712
            )
        )
        rules = result.scalars().all()
    except Exception:
        logger.exception("Failed to load ticket_status_change rules")
        return

    if not rules:
        return

    try:
        template = template_env.get_template("ticket_status_change.html")
    except Exception:
        logger.exception("Failed to load ticket_status_change.html template")
        return

    office_name = ticket.office.location_name if ticket.office else "N/A"
    assigned_to = ticket.assigned_to.name if ticket.assigned_to else None

    for rule in rules:
        for recipient in rule.recipient_emails or []:
            try:
                html = template.render(
                    subject=ticket.subject,
                    office_name=office_name,
                    old_status=old_status.replace("_", " ").title(),
                    new_status=new_status.replace("_", " ").title(),
                    assigned_to=assigned_to,
                    updated_by=updated_by_name,
                )
                email_subject = f"Ticket Status Update: {ticket.subject}"
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
                logger.exception("Failed to send ticket_status_change email to %s", recipient)

    try:
        await db.commit()
    except Exception:
        logger.exception("Failed to commit EmailLog rows for ticket status change")
        await db.rollback()


async def send_ticket_closed_email(
    db: AsyncSession,
    ticket: MaintenanceTicket,
    closed_by_name: str,
) -> None:
    """Send closure confirmation to the ticket creator."""
    if not ticket.created_by or not ticket.created_by.email:
        return

    try:
        template = template_env.get_template("ticket_closed.html")
    except Exception:
        logger.exception("Failed to load ticket_closed.html template")
        return

    from datetime import datetime
    office_name = ticket.office.location_name if ticket.office else "N/A"
    category_name = ticket.category.name if ticket.category else "N/A"

    try:
        html = template.render(
            subject=ticket.subject,
            office_name=office_name,
            category=category_name,
            closed_by=closed_by_name,
            closed_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        email_subject = f"Your ticket has been resolved: {ticket.subject}"
        await send_email(ticket.created_by.email, email_subject, html)
    except Exception:
        logger.exception("Failed to send ticket_closed email for ticket %s", ticket.id)


async def send_ticket_assigned_email(
    db: AsyncSession,
    ticket: MaintenanceTicket,
    assignee_email: str,
) -> None:
    """Send assignment notification directly to the assignee."""
    try:
        template = template_env.get_template("ticket_assigned.html")
    except Exception:
        logger.exception("Failed to load ticket_assigned.html template")
        return

    office_name = ticket.office.location_name if ticket.office else "N/A"
    category_name = ticket.category.name if ticket.category else "N/A"
    created_by = ticket.created_by.display_name if ticket.created_by else "N/A"

    try:
        html = template.render(
            subject=ticket.subject,
            office_name=office_name,
            priority=ticket.priority.title(),
            status=ticket.status.replace("_", " ").title(),
            category=category_name,
            created_by=created_by,
            description=ticket.description or "",
        )
        email_subject = f"Ticket Assigned to You: {ticket.subject}"
        await send_email(assignee_email, email_subject, html)
    except Exception:
        logger.exception("Failed to send ticket_assigned email to %s", assignee_email)


async def send_mention_emails(
    db: AsyncSession,
    note: "TicketNote",
    ticket: MaintenanceTicket,
) -> None:
    """Parse @word tokens from note_text, match users by display_name, send mention emails."""
    import re
    from app.models.user import User

    tokens = re.findall(r"@(\w+)", note.note_text)
    if not tokens:
        return

    try:
        template = template_env.get_template("ticket_mention.html")
    except Exception:
        logger.exception("Failed to load ticket_mention.html template")
        return

    office_name = ticket.office.location_name if ticket.office else "N/A"
    note_preview = note.note_text[:200] + ("..." if len(note.note_text) > 200 else "")

    notified: set[str] = set()
    for token in tokens:
        try:
            result = await db.execute(
                select(User).where(
                    User.display_name.ilike(f"%{token}%"),
                    User.is_active.is_(True),
                )
            )
            matched_users = result.scalars().all()
        except Exception:
            logger.exception("Failed to query users for mention token @%s", token)
            continue

        for user in matched_users:
            if not user.email or user.email in notified:
                continue
            # Skip the note author
            if note.created_by_id and user.id == note.created_by_id:
                continue
            try:
                html = template.render(
                    ticket_subject=ticket.subject,
                    office_name=office_name,
                    note_preview=note_preview,
                    mentioned_name=user.display_name,
                )
                email_subject = f"You were mentioned in a ticket: {ticket.subject}"
                await send_email(user.email, email_subject, html)
                notified.add(user.email)
                logger.info("Mention email sent to %s for ticket %s", user.email, ticket.id)
            except Exception:
                logger.exception("Failed to send mention email to %s", user.email)


# Avoid circular import for type hint
from app.models.maintenance_ticket import TicketNote  # noqa: E402

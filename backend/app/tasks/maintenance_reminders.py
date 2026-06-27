"""Maintenance task reminders.

Scans maintenance tasks that have reminders enabled and whose ``next_due_date``
falls within the configured lead time, then emails the task's recipients plus the
assigned vendor's contact email. De-duplicates via :class:`EmailLog` so a task is
only emailed once per due cycle.
"""
from datetime import date, timedelta

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import EmailLog, MaintenanceTask
from app.models.maintenance import MAINTENANCE_CATEGORIES
from app.utils.email_client import send_email

template_env = Environment(loader=FileSystemLoader("app/templates"))


def _category_label(category: str) -> str:
    cat = MAINTENANCE_CATEGORIES.get(category)
    return cat["label"] if cat else category


async def check_maintenance_reminders():
    async with async_session() as db:
        today = date.today()
        result = await db.execute(
            select(MaintenanceTask)
            .options(
                selectinload(MaintenanceTask.vendor),
                selectinload(MaintenanceTask.office),
            )
            .where(
                MaintenanceTask.reminder_enabled.is_(True),
                MaintenanceTask.next_due_date.is_not(None),
                MaintenanceTask.next_due_date >= today,
                MaintenanceTask.status != "completed",
            )
        )
        tasks = result.scalars().all()
        template = template_env.get_template("maintenance_reminder.html")

        sent_count = 0
        for task in tasks:
            days_until = (task.next_due_date - today).days
            if days_until > task.reminder_days_before:
                continue

            recipients = list(task.reminder_recipients or [])
            if task.vendor and task.vendor.contact_email:
                recipients.append(task.vendor.contact_email)
            # De-duplicate while preserving order.
            recipients = list(dict.fromkeys(r for r in recipients if r))
            if not recipients:
                continue

            subject = (
                f"[Maintenance Due] {_category_label(task.category)}: "
                f"{task.title[:40]} - {days_until} days"
            )
            html = template.render(
                category=_category_label(task.category),
                title=task.title,
                frequency=task.frequency or "N/A",
                due_date=str(task.next_due_date),
                status=task.status,
                days_until=days_until,
                office=task.office.location_name if task.office else "N/A",
                vendor=task.vendor.company_name if task.vendor else "Unassigned",
            )

            for recipient in recipients:
                existing = await db.execute(
                    select(EmailLog).where(
                        EmailLog.sent_to == recipient,
                        EmailLog.subject == subject,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                ok = await send_email(recipient, subject, html)
                db.add(
                    EmailLog(
                        sent_to=recipient,
                        subject=subject,
                        body=html,
                        status="sent" if ok else "failed",
                    )
                )
                sent_count += 1

        await db.commit()
        print(f"[MAINTENANCE REMINDERS] {len(tasks)} due tasks, {sent_count} emails sent")

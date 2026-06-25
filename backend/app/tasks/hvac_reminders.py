from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from jinja2 import Environment, FileSystemLoader
from app.database import async_session
from app.models import HvacContract, HqPmTask, EmailReminderRule, EmailLog
from app.utils.email_client import send_email

template_env = Environment(loader=FileSystemLoader("app/templates"))


async def check_hvac_reminders():
    async with async_session() as db:
        rules = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type == "hvac_service",
                EmailReminderRule.is_active == True,
            )
        )
        rules = rules.scalars().all()

        for rule in rules:
            today = date.today()
            cutoff = today + timedelta(days=rule.days_before)

            result = await db.execute(
                select(HvacContract).options(joinedload(HvacContract.manager)).where(
                    HvacContract.next_service_date != None,
                    HvacContract.next_service_date <= cutoff,
                    HvacContract.next_service_date >= today,
                )
            )
            contracts = result.unique().scalars().all()

            template = template_env.get_template("hvac_service_reminder.html")

            for contract in contracts:
                for recipient in rule.recipient_emails:
                    existing = await db.execute(
                        select(EmailLog).where(
                            EmailLog.rule_id == rule.id,
                            EmailLog.sent_to == recipient,
                            EmailLog.subject.contains(contract.office_name or ""),
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    days_until = (contract.next_service_date - today).days

                    html = template.render(
                        office_name=contract.office_name or f"Office #{contract.office_number}",
                        hvac_company=contract.hvac_company or "N/A",
                        contact=contract.contact or "N/A",
                        frequency=contract.frequency or "N/A",
                        next_service_date=str(contract.next_service_date),
                        manager_name=contract.manager.name if contract.manager else "N/A",
                        days_until=days_until,
                    )

                    subject = f"[HVAC Service Due] {contract.office_name} - {days_until} days"
                    sent = await send_email(recipient, subject, html)

                    log = EmailLog(
                        rule_id=rule.id, sent_to=recipient, subject=subject,
                        body=html, status="sent" if sent else "failed",
                    )
                    db.add(log)

            await db.commit()
            print(f"[HVAC REMINDERS] Processed rule '{rule.rule_name}': {len(contracts)} contracts found")


async def check_hq_pm_reminders():
    async with async_session() as db:
        rules = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type == "hq_pm",
                EmailReminderRule.is_active == True,
            )
        )
        rules = rules.scalars().all()

        for rule in rules:
            today = date.today()
            cutoff = today + timedelta(days=rule.days_before)

            result = await db.execute(
                select(HqPmTask).where(
                    HqPmTask.next_due_date != None,
                    HqPmTask.next_due_date <= cutoff,
                    HqPmTask.next_due_date >= today,
                    HqPmTask.status != "Completed",
                )
            )
            tasks = result.scalars().all()

            template = template_env.get_template("hq_pm_reminder.html")

            for task in tasks:
                for recipient in rule.recipient_emails:
                    existing = await db.execute(
                        select(EmailLog).where(
                            EmailLog.rule_id == rule.id,
                            EmailLog.sent_to == recipient,
                            EmailLog.subject.contains(task.task_description[:50]),
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    days_until = (task.next_due_date - today).days

                    html = template.render(
                        equipment_category=task.equipment_category,
                        task_description=task.task_description,
                        frequency=task.frequency or "N/A",
                        due_date=str(task.next_due_date),
                        status=task.status,
                        days_until=days_until,
                    )

                    subject = f"[HQ PM Due] {task.equipment_category}: {task.task_description[:40]} - {days_until} days"
                    sent = await send_email(recipient, subject, html)

                    log = EmailLog(
                        rule_id=rule.id, sent_to=recipient, subject=subject,
                        body=html, status="sent" if sent else "failed",
                    )
                    db.add(log)

            await db.commit()
            print(f"[HQ PM REMINDERS] Processed rule '{rule.rule_name}': {len(tasks)} tasks found")

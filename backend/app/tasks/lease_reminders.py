from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from jinja2 import Environment, FileSystemLoader
from app.database import async_session
from app.models import Lease, EmailReminderRule, EmailLog
from app.utils.email_client import send_email
from app.services.webhook_service import dispatch_webhook

template_env = Environment(loader=FileSystemLoader("app/templates"))


async def check_lease_reminders():
    async with async_session() as db:
        rules = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type.in_(["lease_expiration", "lease_notice"]),
                EmailReminderRule.is_active == True,
            )
        )
        rules = rules.scalars().all()

        for rule in rules:
            today = date.today()
            cutoff = today + timedelta(days=rule.days_before)

            if rule.rule_type == "lease_expiration":
                query = select(Lease).options(joinedload(Lease.manager)).where(
                    Lease.lease_expiration != None,
                    Lease.lease_expiration <= cutoff,
                    Lease.lease_expiration >= today,
                )
                if rule.organization_id is not None:
                    query = query.where(Lease.organization_id == rule.organization_id)
                template = template_env.get_template("lease_expiration_reminder.html")
            else:
                query = select(Lease).options(joinedload(Lease.manager)).where(
                    Lease.lease_notice_date != None,
                    Lease.lease_notice_date <= cutoff,
                    Lease.lease_notice_date >= today,
                    Lease.notice_given_date == None,
                )
                if rule.organization_id is not None:
                    query = query.where(Lease.organization_id == rule.organization_id)
                template = template_env.get_template("lease_notice_reminder.html")

            result = await db.execute(query)
            leases = result.unique().scalars().all()

            for lease in leases:
                for recipient in rule.recipient_emails:
                    existing = await db.execute(
                        select(EmailLog).where(
                            EmailLog.rule_id == rule.id,
                            EmailLog.sent_to == recipient,
                            EmailLog.subject.contains(lease.lease_name),
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    ref_date = lease.lease_expiration if rule.rule_type == "lease_expiration" else lease.lease_notice_date
                    days_until = (ref_date - today).days if ref_date else 0

                    html = template.render(
                        lease_name=lease.lease_name,
                        days_until=days_until,
                        expiration_date=str(lease.lease_expiration or "N/A"),
                        manager_name=lease.manager.name if lease.manager else "N/A",
                        lessor_name=lease.lessor_name or "N/A",
                        notice_period=lease.notice_period or "N/A",
                        notice_date=str(lease.lease_notice_date or "N/A"),
                        notice_given=str(lease.notice_given_date or "Not yet"),
                    )

                    subject = f"[{rule.rule_type.replace('_', ' ').title()}] {lease.lease_name} - {days_until} days"
                    sent = await send_email(recipient, subject, html)

                    log = EmailLog(
                        rule_id=rule.id,
                        sent_to=recipient,
                        subject=subject,
                        body=html,
                        status="sent" if sent else "failed",
                    )
                    db.add(log)

                # Dispatch lease.expiring webhook once per lease (best-effort)
                if rule.rule_type == "lease_expiration" and lease.organization_id is not None:
                    try:
                        ref_date = lease.lease_expiration
                        days_until = (ref_date - today).days if ref_date else 0
                        await dispatch_webhook(
                            db,
                            lease.organization_id,
                            "lease.expiring",
                            {
                                "lease_id": str(lease.id),
                                "lease_name": lease.lease_name,
                                "expiration_date": str(lease.lease_expiration),
                                "days_until_expiration": days_until,
                            },
                        )
                    except Exception:
                        pass

            await db.commit()
            print(f"[LEASE REMINDERS] Processed rule '{rule.rule_name}': {len(leases)} leases found")


from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from jinja2 import Environment, FileSystemLoader
from app.database import async_session
from app.models import Lease, EmailReminderRule, EmailLog
from app.utils.email_client import send_email
from app.services.webhook_service import dispatch_webhook
from app.services.email_rule_engine import (
    DigestBuffer,
    acknowledge_link_html,
    due_escalation_level,
    escalation_recipients,
    get_or_create_acknowledgement,
    resolve_recipients,
)

template_env = Environment(loader=FileSystemLoader("app/templates"))


async def check_lease_reminders():
    async with async_session() as db:
        rules = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type.in_(["lease_expiration", "lease_notice_date", "lease_notice"]),
                EmailReminderRule.is_active == True,
            )
        )
        rules = rules.scalars().all()

        for rule in rules:
            today = date.today()
            cutoff = today + timedelta(days=rule.days_before)
            is_expiration = rule.rule_type == "lease_expiration"

            if is_expiration:
                query = select(Lease).options(joinedload(Lease.manager)).where(
                    Lease.lease_expiration != None,
                    Lease.lease_expiration <= cutoff,
                    Lease.lease_expiration >= today,
                )
                template = template_env.get_template("lease_expiration_reminder.html")
            else:
                query = select(Lease).options(joinedload(Lease.manager)).where(
                    Lease.lease_notice_date != None,
                    Lease.lease_notice_date <= cutoff,
                    Lease.lease_notice_date >= today,
                    Lease.notice_given_date == None,
                )
                template = template_env.get_template("lease_notice_reminder.html")

            if rule.organization_id is not None:
                query = query.where(Lease.organization_id == rule.organization_id)

            result = await db.execute(query)
            leases = result.unique().scalars().all()

            base_recipients = await resolve_recipients(db, rule)
            digest = DigestBuffer() if rule.delivery_mode != "immediate" else None
            processed = 0

            for lease in leases:
                ref_date = lease.lease_expiration if is_expiration else lease.lease_notice_date
                days_until = (ref_date - today).days if ref_date else 0
                subject = f"[{rule.rule_type.replace('_', ' ').title()}] {lease.lease_name} - {days_until} days"

                # Notice-state row drives dedup, escalation and acknowledgement.
                ack = await get_or_create_acknowledgement(
                    db, rule, entity_type="lease", entity_id=lease.id, subject=subject
                )
                # Stop entirely once a recipient has acknowledged this notice.
                if ack.acknowledged_at is not None:
                    continue

                days_since_first = (today - ack.first_sent_at.date()).days
                level = due_escalation_level(rule, days_since_first)
                # Only emit when a new step has come due (level 0 is the initial notice).
                if level <= ack.escalation_level:
                    continue

                recipients = base_recipients + escalation_recipients(rule, level)
                # De-dupe while preserving order (escalation list may overlap base).
                seen: set[str] = set()
                recipients = [r for r in recipients if not (r.lower() in seen or seen.add(r.lower()))]
                if not recipients:
                    continue

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
                if rule.require_acknowledgement:
                    html += acknowledge_link_html(ack)

                step_subject = subject if level == 0 else f"[ESCALATION {level}] {subject}"

                if digest is not None:
                    fragment = (
                        f"<li><strong>{lease.lease_name}</strong> &mdash; {days_until} days "
                        f"(escalation level {level})</li>"
                    )
                    digest.add(recipients, fragment)
                    # In digest mode we record the step now; the combined email is
                    # sent once at the end of the rule's processing.
                    for recipient in recipients:
                        db.add(EmailLog(
                            rule_id=rule.id, sent_to=recipient, subject=step_subject,
                            body=html, status="queued", escalation_level=level,
                        ))
                else:
                    for recipient in recipients:
                        sent = await send_email(recipient, step_subject, html)
                        db.add(EmailLog(
                            rule_id=rule.id, sent_to=recipient, subject=step_subject,
                            body=html, status="sent" if sent else "failed",
                            escalation_level=level,
                        ))

                ack.escalation_level = level
                processed += 1

                # Dispatch lease.expiring webhook once per lease (best-effort)
                if is_expiration and lease.organization_id is not None and level == 0:
                    try:
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

            if digest is not None and not digest.is_empty:
                intro = f"<p>Reminder digest for rule <strong>{rule.rule_name}</strong>:</p>"
                await digest.flush(subject=f"[Digest] {rule.rule_name}", intro=intro)

            await db.commit()
            print(f"[LEASE REMINDERS] Processed rule '{rule.rule_name}': {processed} notices sent")

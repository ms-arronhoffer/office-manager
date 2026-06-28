"""APScheduler task: COI (insurance certificate) expiration reminders.

Re-implemented to be driven by admin-configured ``coi_expiration`` email rules
(thresholds + recipients), instead of hardcoded alert windows. Each active rule
is evaluated through the shared :mod:`app.services.email_rule_engine`, giving COI
reminders the same recipient-resolution, escalation, acknowledgement and digest
behaviour as lease reminders. The in-app notification to org admins is preserved
as one additional delivery channel.

Vendor-held certificates include a deep link to the vendor portal's self-service
re-upload page so the vendor can submit a renewed certificate directly.
"""

import logging
from datetime import date, timedelta

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.models import EmailReminderRule, EmailLog
from app.models.insurance_certificate import InsuranceCertificate
from app.models.user import User
from app.services.email_rule_engine import (
    DigestBuffer,
    acknowledge_link_html,
    due_escalation_level,
    escalation_recipients,
    get_or_create_acknowledgement,
    resolve_recipients,
)
from app.services.vendor_portal_links import ensure_portal_token, vendor_reupload_url
from app.utils.email_client import send_email
from app.utils.notifications import create_notification

log = logging.getLogger(__name__)

# Rule types this task consumes. ``coi_expiration`` covers the expiry window;
# the engine's ``days_before`` threshold makes a separate "expiring" type
# unnecessary.
COI_RULE_TYPES = ("coi_expiration",)

template_env = Environment(loader=FileSystemLoader("app/templates"))


def _holder_name(cert: InsuranceCertificate) -> str:
    if cert.vendor:
        return cert.vendor.company_name
    if cert.landlord:
        return cert.landlord.landlord_company or cert.landlord.contact_name or "Unknown"
    return "Unknown"


async def check_insurance_expirations() -> None:
    """Runs daily via APScheduler. Evaluates active ``coi_expiration`` rules."""
    async with async_session() as db:
        result = await db.execute(
            select(EmailReminderRule).where(
                EmailReminderRule.rule_type.in_(COI_RULE_TYPES),
                EmailReminderRule.is_active.is_(True),
            )
        )
        rules = result.scalars().all()
        if not rules:
            log.info("No active COI expiration rules configured")
            return

        for rule in rules:
            try:
                await _process_rule(db, rule)
            except Exception:
                log.exception("Failed to process COI rule %s", rule.id)
                await db.rollback()


async def _process_rule(db, rule: EmailReminderRule) -> None:
    template = template_env.get_template("coi_expiration_reminder.html")
    today = date.today()
    cutoff = today + timedelta(days=rule.days_before)

    query = (
        select(InsuranceCertificate)
        .options(
            joinedload(InsuranceCertificate.vendor),
            joinedload(InsuranceCertificate.landlord),
        )
        .where(
            InsuranceCertificate.expiration_date.is_not(None),
            InsuranceCertificate.expiration_date >= today,
            InsuranceCertificate.expiration_date <= cutoff,
        )
    )
    if rule.organization_id is not None:
        query = query.where(InsuranceCertificate.organization_id == rule.organization_id)

    certs = (await db.execute(query)).scalars().unique().all()

    base_recipients = await resolve_recipients(db, rule)
    digest = DigestBuffer() if rule.delivery_mode != "immediate" else None

    # Pre-load admins per org so we can mirror the legacy in-app notification.
    admin_ids_by_org: dict = {}

    async def admins_for(org_id) -> list:
        if org_id is None:
            return []
        if org_id not in admin_ids_by_org:
            res = await db.execute(
                select(User.id).where(
                    User.role == "admin",
                    User.is_active.is_(True),
                    User.organization_id == org_id,
                )
            )
            admin_ids_by_org[org_id] = [row[0] for row in res.all()]
        return admin_ids_by_org[org_id]

    processed = 0
    for cert in certs:
        days_until = (cert.expiration_date - today).days
        holder_name = _holder_name(cert)
        cert_type = cert.certificate_type.replace("_", " ").title()
        subject = f"[COI Expiration] {holder_name} - {cert_type} expires in {days_until} days"

        ack = await get_or_create_acknowledgement(
            db, rule, entity_type="insurance_certificate", entity_id=cert.id, subject=subject
        )
        if ack.acknowledged_at is not None:
            continue

        days_since_first = (today - ack.first_sent_at.date()).days
        level = due_escalation_level(rule, days_since_first)
        if level <= ack.escalation_level:
            continue

        recipients = base_recipients + escalation_recipients(rule, level)
        seen: set[str] = set()
        recipients = [r for r in recipients if not (r.lower() in seen or seen.add(r.lower()))]

        # Deep-link vendor-held certs to the self-service re-upload page.
        reupload_url = None
        if cert.vendor is not None:
            token = ensure_portal_token(cert.vendor)
            reupload_url = vendor_reupload_url(token)

        html = template.render(
            holder_name=holder_name,
            certificate_type=cert_type,
            policy_number=cert.policy_number or "N/A",
            insurer=cert.insurer or "N/A",
            expiration_date=str(cert.expiration_date),
            days_until=days_until,
            reupload_url=reupload_url,
        )
        if rule.require_acknowledgement:
            html += acknowledge_link_html(ack)

        step_subject = subject if level == 0 else f"[ESCALATION {level}] {subject}"

        if recipients:
            if digest is not None:
                fragment = (
                    f"<li><strong>{holder_name}</strong> &mdash; {cert_type} "
                    f"expires in {days_until} days (escalation level {level})</li>"
                )
                digest.add(recipients, fragment)
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

        # In-app notification to org admins — one additional delivery channel,
        # fired once on the initial notice (level 0).
        if level == 0:
            body = (
                f"{cert_type} policy (#{cert.policy_number or 'N/A'}) for {holder_name} "
                f"expires {cert.expiration_date}."
            )
            for admin_id in await admins_for(cert.organization_id):
                try:
                    await create_notification(
                        db,
                        user_id=admin_id,
                        kind="insurance_expiration",
                        title=f"Insurance cert expiring in {days_until} days: {holder_name}",
                        body=body,
                        entity_type="insurance_certificate",
                        entity_id=cert.id,
                    )
                except Exception:
                    log.exception("Failed to create COI notification for admin %s", admin_id)

        ack.escalation_level = level
        processed += 1

    if digest is not None and not digest.is_empty:
        intro = f"<p>COI reminder digest for rule <strong>{rule.rule_name}</strong>:</p>"
        await digest.flush(subject=f"[Digest] {rule.rule_name}", intro=intro)

    await db.commit()
    log.info("[COI REMINDERS] Processed rule '%s': %d notices", rule.rule_name, processed)

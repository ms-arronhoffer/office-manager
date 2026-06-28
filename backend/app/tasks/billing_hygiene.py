"""Daily billing hygiene job.

Handles trial expiry warnings, conversion drip emails, and past-due dunning
reminders. Runs at 06:00 UTC every day.

Deduplication is done by checking the EmailLog table for recent sends of the
same subject to the same recipient (within the last 20 hours), preventing
duplicate emails when the job is retried or the scheduler restarts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.email import EmailLog
from app.models.organization import Organization
from app.models.user import User
from app.services import entitlements as ent
from app.utils.datetime_utils import as_utc as _ensure_utc
from app.utils.email_client import send_email

logger = logging.getLogger(__name__)


async def _already_sent(db: AsyncSession, email: str, template_name: str) -> bool:
    """Return True if we sent this template to this address in the last 20h.

    Uses the template name stored in the EmailLog body (``template:<name>``)
    rather than a subject prefix, making deduplication unambiguous.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
    result = await db.execute(
        select(EmailLog).where(
            EmailLog.sent_to == email,
            EmailLog.body == f"template:{template_name}",
            EmailLog.sent_at >= cutoff,
        )
    )
    return result.scalar_one_or_none() is not None


async def _log_sent(db: AsyncSession, email: str, subject: str, template: str) -> None:
    """Record a sent email in the EmailLog for deduplication."""
    log = EmailLog(
        sent_to=email,
        subject=subject,
        body=f"template:{template}",
        status="sent",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(log)
    try:
        await db.commit()
    except Exception:
        await db.rollback()


async def _get_org_admin_emails(db: AsyncSession, org_id) -> list[str]:
    result = await db.execute(
        select(User.email).where(
            User.organization_id == org_id,
            User.role == "admin",
            User.is_active.is_(True),
        )
    )
    return [r[0] for r in result.all()]


async def _send_trial_email(
    db: AsyncSession,
    org: Organization,
    template_name: str,
    subject: str,
    extra_ctx: dict | None = None,
) -> None:
    """Send a trial-lifecycle email to all org admins (deduplicated)."""
    try:
        from jinja2 import Environment, FileSystemLoader
        from app.config import settings

        env = Environment(loader=FileSystemLoader("app/templates"))
        template = env.get_template(template_name)
        ctx = {
            "org_name": org.name,
            "upgrade_url": f"{settings.FRONTEND_URL}/billing",
            "billing_url": f"{settings.FRONTEND_URL}/billing",
        }
        if org.trial_ends_at:
            ctx["trial_ends_at"] = org.trial_ends_at.strftime("%B %d, %Y")
        if extra_ctx:
            ctx.update(extra_ctx)
        html_body = template.render(**ctx)

        recipients = await _get_org_admin_emails(db, org.id)
        for email in recipients:
            if not await _already_sent(db, email, template_name):
                sent = await send_email(to=email, subject=subject, html_body=html_body)
                if sent:
                    await _log_sent(db, email, subject, template_name)
    except Exception as e:
        logger.warning(
            "Billing hygiene failed to send %s for %s: %s", template_name, org.name, e
        )


async def run_billing_hygiene() -> None:
    """Main entry point called by the scheduler."""
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # Fetch all orgs with an active trial (no paid subscription)
        result = await db.execute(
            select(Organization).where(
                Organization.is_active.is_(True),
                Organization.trial_ends_at.is_not(None),
                Organization.stripe_subscription_id.is_(None),
                Organization.payment_status == "active",
            )
        )
        trial_orgs = result.scalars().all()

        for org in trial_orgs:
            trial_end = _ensure_utc(org.trial_ends_at)
            days_remaining = (trial_end - now).days
            days_since_signup = (now - _ensure_utc(org.created_at)).days

            # Trial already expired — send expiry email
            if now > trial_end:
                await _send_trial_email(
                    db, org,
                    "billing_trial_expired.html",
                    f"Your SwiftLease trial has ended",
                )
                continue

            # 1-day warning
            if days_remaining <= 1:
                await _send_trial_email(
                    db, org,
                    "billing_trial_expiring.html",
                    f"Final reminder: Your SwiftLease trial ends tomorrow",
                    extra_ctx={"days_remaining": max(0, days_remaining)},
                )
            # 7-day warning
            elif days_remaining <= 7:
                await _send_trial_email(
                    db, org,
                    "billing_trial_expiring.html",
                    f"Your SwiftLease trial expires in {days_remaining} day{'s' if days_remaining != 1 else ''}",
                    extra_ctx={"days_remaining": days_remaining},
                )

            # Conversion drip: day 7 of trial
            if 7 <= days_since_signup < 8:
                await _send_trial_email(
                    db, org,
                    "billing_trial_day7.html",
                    "You're 7 days into your SwiftLease trial!",
                )
            # Conversion drip: day 14 of trial
            elif 14 <= days_since_signup < 15:
                await _send_trial_email(
                    db, org,
                    "billing_trial_day14.html",
                    "Halfway through your SwiftLease trial",
                )
            # Conversion drip: day 25 of trial (5 days before 30-day trial ends)
            elif 25 <= days_since_signup < 26:
                await _send_trial_email(
                    db, org,
                    "billing_trial_day25.html",
                    "5 days left in your SwiftLease trial",
                )

        # Past-due dunning: orgs beyond the grace period
        grace_cutoff = now - timedelta(days=ent.PAST_DUE_GRACE_DAYS)
        past_due_result = await db.execute(
            select(Organization).where(
                Organization.is_active.is_(True),
                Organization.payment_status == "past_due",
            )
        )
        past_due_orgs = past_due_result.scalars().all()

        for org in past_due_orgs:
            if org.past_due_since is None:
                continue
            past_due_ts = _ensure_utc(org.past_due_since)
            days_past_due = (now - past_due_ts).days
            if days_past_due >= ent.PAST_DUE_GRACE_DAYS - 2:
                # 2 days before lockout — send urgent dunning notice
                try:
                    from jinja2 import Environment, FileSystemLoader
                    from app.config import settings
                    env = Environment(loader=FileSystemLoader("app/templates"))
                    template = env.get_template("billing_payment_failed.html")
                    html = template.render(
                        org_name=org.name,
                        grace_days=max(0, ent.PAST_DUE_GRACE_DAYS - days_past_due),
                        billing_url=f"{settings.FRONTEND_URL}/billing",
                    )
                    recipients = await _get_org_admin_emails(db, org.id)
                    for email in recipients:
                        subject = f"Urgent: Update payment for {org.name} to avoid lockout"
                        if not await _already_sent(db, email, "billing_payment_failed.html"):
                            sent = await send_email(to=email, subject=subject, html_body=html)
                            if sent:
                                await _log_sent(db, email, subject, "billing_payment_failed.html")
                except Exception as e:
                    logger.warning("Dunning email failed for %s: %s", org.name, e)

    logger.info("Billing hygiene complete")

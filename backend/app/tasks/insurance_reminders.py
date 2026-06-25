"""APScheduler task: alert admins when insurance certificates are expiring soon."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database import async_session
from app.models.insurance_certificate import InsuranceCertificate
from app.models.user import User
from app.utils.notifications import create_notification

log = logging.getLogger(__name__)

_ALERT_DAYS = [30, 14, 7]  # Warn at 30, 14, and 7 days before expiration


async def check_insurance_expirations() -> None:
    """
    Runs daily at 8:00 AM via APScheduler.

    For each InsuranceCertificate with an expiration_date:
      - Alerts org admins when expiration is within 30, 14, or 7 days.
    """
    async with async_session() as db:
        today = date.today()
        # Find all certs expiring within the largest window
        cutoff = today + timedelta(days=max(_ALERT_DAYS))

        try:
            result = await db.execute(
                select(InsuranceCertificate)
                .options(
                    joinedload(InsuranceCertificate.vendor),
                    joinedload(InsuranceCertificate.landlord),
                )
                .where(
                    InsuranceCertificate.expiration_date.is_not(None),
                    InsuranceCertificate.expiration_date >= today,
                    InsuranceCertificate.expiration_date <= cutoff,
                    InsuranceCertificate.organization_id.is_not(None),
                )
            )
            certs = result.scalars().unique().all()
        except Exception:
            log.exception("Failed to query insurance certificates for expiration check")
            return

        if not certs:
            log.info("No insurance certificates expiring soon")
            return

        log.info("Found %d insurance certificates expiring within %d days", len(certs), max(_ALERT_DAYS))

        # Pre-load admins per org to avoid N+1
        org_ids = {c.organization_id for c in certs}
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
                log.exception("Failed to query admins for org %s", org_id)
                org_admin_ids[org_id] = []

        for cert in certs:
            days_until = (cert.expiration_date - today).days

            # Only notify at the specific thresholds
            if days_until not in _ALERT_DAYS:
                continue

            holder_name = (
                cert.vendor.company_name if cert.vendor
                else cert.landlord.landlord_company or cert.landlord.contact_name if cert.landlord
                else "Unknown"
            )
            title = f"Insurance cert expiring in {days_until} days: {holder_name}"
            body = (
                f"{cert.certificate_type.replace('_', ' ').title()} policy "
                f"(#{cert.policy_number or 'N/A'}) expires {cert.expiration_date}."
            )

            for admin_id in org_admin_ids.get(cert.organization_id, []):
                try:
                    await create_notification(
                        db,
                        user_id=admin_id,
                        kind="insurance_expiration",
                        title=title,
                        body=body,
                        entity_type="insurance_certificate",
                        entity_id=cert.id,
                    )
                except Exception:
                    log.exception("Failed to create insurance expiration notification for admin %s", admin_id)

        try:
            await db.commit()
        except Exception:
            log.exception("Failed to commit insurance expiration notifications")
            await db.rollback()

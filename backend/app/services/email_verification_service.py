from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.email import EmailLog
from app.models.user import User
from app.utils.email_client import send_email

logger = logging.getLogger(__name__)

EMAIL_VERIFICATION_EXPIRY_HOURS = 24


async def issue_verification_token(user: User, db: AsyncSession) -> str:
    token = secrets.token_urlsafe(48)
    user.email_verification_token = token
    user.email_verification_expires_at = datetime.now(timezone.utc) + timedelta(hours=EMAIL_VERIFICATION_EXPIRY_HOURS)
    await db.commit()
    return token


def send_verification_email(user: User, token: str, background_tasks: BackgroundTasks) -> None:
    background_tasks.add_task(
        _deliver_verification_email,
        email=user.email,
        display_name=user.display_name,
        token=token,
    )


async def _deliver_verification_email(*, email: str, display_name: str, token: str) -> None:
    sent = False
    error_detail: str | None = None
    subject = "Verify your email address"
    verify_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email/{token}"
    html = (
        f"<p>Hello {display_name},</p>"
        f"<p>Please verify your email address to finish setting up your account.</p>"
        f"<p><a href=\"{verify_url}\">Verify email</a></p>"
        f"<p>This link expires in {EMAIL_VERIFICATION_EXPIRY_HOURS} hours.</p>"
    )
    try:
        sent = bool(await send_email(to=email, subject=subject, html_body=html))
        if not sent:
            error_detail = (
                "send_email returned False — SMTP is not configured "
                "(SMTP_HOST unset) or the provider rejected the message."
            )
            logger.warning("Verification email not delivered to %s: %s", email, error_detail)
    except Exception as exc:  # pragma: no cover - email best-effort
        error_detail = str(exc)
        logger.exception("Verification email send raised for %s", email)

    async with async_session() as db:
        try:
            db.add(
                EmailLog(
                    rule_id=None,
                    sent_to=email,
                    subject=subject,
                    body=error_detail,
                    status="sent" if sent else "failed",
                )
            )
            await db.commit()
        except Exception:  # pragma: no cover - logging best-effort
            logger.exception("Failed to write EmailLog for verification email to %s", email)
            await db.rollback()

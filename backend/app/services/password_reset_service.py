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

RESET_TOKEN_EXPIRY_HOURS = 2


async def issue_password_reset_token(user: User, db: AsyncSession) -> str:
    token = secrets.token_urlsafe(48)
    user.password_reset_token = token
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRY_HOURS)
    await db.commit()
    return token


def send_password_reset_email(
    user: User,
    token: str,
    background_tasks: BackgroundTasks,
    *,
    subject: str = "Password Reset Request",
    intro_html: str | None = None,
    footer_html: str | None = None,
) -> None:
    background_tasks.add_task(
        _deliver_password_reset_email,
        email=user.email,
        token=token,
        subject=subject,
        intro_html=intro_html
        or "<p>You requested a password reset for your account.</p>",
        footer_html=footer_html
        or "<p>If you did not request this, you can safely ignore this email.</p>",
    )


async def _deliver_password_reset_email(
    *,
    email: str,
    token: str,
    subject: str,
    intro_html: str,
    footer_html: str,
) -> None:
    sent = False
    error_detail: str | None = None
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password/{token}"
    html = (
        f"{intro_html}"
        f"<p><a href=\"{reset_url}\">Set your password</a></p>"
        f"<p>If the button does not work, use this reset token: <strong>{token}</strong></p>"
        f"<p>This link expires in {RESET_TOKEN_EXPIRY_HOURS} hours.</p>"
        f"{footer_html}"
    )
    try:
        sent = bool(await send_email(to=email, subject=subject, html_body=html))
        if not sent:
            error_detail = (
                "send_email returned False — SMTP is not configured "
                "(SMTP_HOST unset) or the provider rejected the message."
            )
            logger.warning("Password reset email not delivered to %s: %s", email, error_detail)
    except Exception as exc:  # pragma: no cover - email best-effort
        error_detail = str(exc)
        logger.exception("Password reset email send raised for %s", email)

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
            logger.exception("Failed to write EmailLog for password reset email to %s", email)
            await db.rollback()

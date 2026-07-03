"""SMS / text-message client (Phase 2.2).

A thin, provider-agnostic SMS sender that mirrors :mod:`app.utils.email_client`:
it degrades gracefully to a logged no-op when no SMS provider is configured, so
the rest of the app can call :func:`send_sms` unconditionally.

The default implementation targets a Twilio-style HTTP API but only activates
when ``SMS_ACCOUNT_SID``/``SMS_AUTH_TOKEN``/``SMS_FROM`` are configured. Without
them (the common case in dev/test) sends are skipped and reported as not
delivered, exactly like email when SMTP is unset.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _configured() -> bool:
    return bool(
        getattr(settings, "SMS_ACCOUNT_SID", None)
        and getattr(settings, "SMS_AUTH_TOKEN", None)
        and getattr(settings, "SMS_FROM", None)
    )


async def send_sms(to: str, body: str) -> bool:
    """Send a text message; return True only when actually delivered.

    Returns False (and logs at INFO) when no phone number is given or the SMS
    provider is not configured, so callers can treat the SMS channel as
    best-effort without special-casing configuration.
    """
    if not to:
        logger.info("SMS skipped (no recipient number)")
        return False
    if not _configured():
        logger.info("SMS skipped (provider not configured): to=%s", to)
        return False

    sid = settings.SMS_ACCOUNT_SID
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"To": to, "From": settings.SMS_FROM, "Body": body}
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(
                url, data=data, auth=(sid, settings.SMS_AUTH_TOKEN)
            )
        if resp.status_code >= 400:
            logger.warning("Failed to send SMS to %s: HTTP %s", to, resp.status_code)
            return False
        return True
    except Exception as e:  # pragma: no cover - network failure path
        logger.warning("Failed to send SMS to %s: %s", to, e)
        return False

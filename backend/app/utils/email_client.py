import logging

import aiosmtplib
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr
from app.config import settings

logger = logging.getLogger(__name__)


class EmailCategory:
    """Logical categories that map to distinct From addresses.

    Keeping these as plain string constants (rather than an Enum) means callers
    can pass the string directly and monkeypatched test doubles that accept
    ``**kwargs`` keep working unchanged.
    """

    SYSTEM = "system"
    NOTIFICATIONS = "notifications"
    WAIVERS = "waivers"


def from_address_for(category: str) -> str:
    """Resolve the From address for a category, falling back to SMTP_FROM.

    A per-category address is only used when it is explicitly configured;
    otherwise every category shares the default SMTP_FROM mailbox so existing
    single-address deployments behave exactly as before.
    """
    mapping = {
        EmailCategory.SYSTEM: settings.SMTP_FROM_SYSTEM,
        EmailCategory.NOTIFICATIONS: settings.SMTP_FROM_NOTIFICATIONS,
        EmailCategory.WAIVERS: settings.SMTP_FROM_WAIVERS,
    }
    return (mapping.get(category) or "").strip() or settings.SMTP_FROM


def _format_sender(address: str, sender_name: str | None) -> str:
    """Combine a display name with the envelope address.

    Recipients judge automated mail largely by who it appears to be from, so an
    organization can put its own name in front of the shared mailbox address.
    """
    if not sender_name:
        return address
    return formataddr((str(Header(sender_name, "utf-8")), address))


async def _send(message: MIMEMultipart) -> bool:
    """Send a MIME message via the configured SMTP server."""
    if not settings.SMTP_HOST:
        logger.info("Email skipped (SMTP not configured): %s", message["Subject"])
        return False

    kwargs: dict = {
        "hostname": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
    }

    # Only use auth + TLS when credentials are provided (external SMTP).
    # The built-in Postfix container needs neither.
    if settings.SMTP_USER:
        kwargs["username"] = settings.SMTP_USER
        kwargs["password"] = settings.SMTP_PASSWORD
        # Port 465 expects implicit TLS (connection wrapped in SSL from the
        # start); every other port (587, 25) uses opportunistic STARTTLS.
        # Sending STARTTLS to a 465 listener — or implicit TLS to a 587
        # listener — fails the handshake, which is why authenticated providers
        # silently weren't delivering mail.
        if settings.SMTP_PORT == 465:
            kwargs["use_tls"] = True
            kwargs["start_tls"] = False
        else:
            kwargs["use_tls"] = False
            kwargs["start_tls"] = True
    else:
        kwargs["use_tls"] = False
        kwargs["start_tls"] = False

    try:
        await aiosmtplib.send(message, **kwargs)
        return True
    except Exception as e:
        logger.warning("Failed to send email to %s: %s", message["To"], e)
        return False


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    *,
    category: str = EmailCategory.SYSTEM,
    from_address: str | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> bool:
    message = MIMEMultipart("alternative")
    message["From"] = _format_sender(
        from_address or from_address_for(category), sender_name
    )
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.attach(MIMEText(html_body, "html"))
    return await _send(message)


async def send_email_with_attachment(
    to: str,
    subject: str,
    html_body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    attachment_content_type: str = "application/pdf",
    *,
    category: str = EmailCategory.SYSTEM,
    from_address: str | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> bool:
    message = MIMEMultipart("mixed")
    message["From"] = _format_sender(
        from_address or from_address_for(category), sender_name
    )
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to

    message.attach(MIMEText(html_body, "html"))

    maintype, subtype = attachment_content_type.split("/", 1)
    attachment = MIMEApplication(attachment_bytes, _subtype=subtype)
    attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    message.attach(attachment)

    return await _send(message)

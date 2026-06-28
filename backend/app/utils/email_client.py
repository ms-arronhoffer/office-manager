import logging

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from app.config import settings

logger = logging.getLogger(__name__)


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


async def send_email(to: str, subject: str, html_body: str) -> bool:
    message = MIMEMultipart("alternative")
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.attach(MIMEText(html_body, "html"))
    return await _send(message)


async def send_email_with_attachment(
    to: str,
    subject: str,
    html_body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    attachment_content_type: str = "application/pdf",
) -> bool:
    message = MIMEMultipart("mixed")
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject

    message.attach(MIMEText(html_body, "html"))

    maintype, subtype = attachment_content_type.split("/", 1)
    attachment = MIMEApplication(attachment_bytes, _subtype=subtype)
    attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    message.attach(attachment)

    return await _send(message)

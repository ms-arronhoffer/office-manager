"""One place to send a customisable, branded email.

Send sites should call :func:`send_templated` rather than composing HTML and
calling the SMTP client directly. Doing so means an organization's branding,
sender name, reply-to address and copy overrides apply everywhere automatically,
and adding a new customisable message is a catalog entry plus one call.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import email_template_service
from app.utils.email_client import EmailCategory, send_email

logger = logging.getLogger(__name__)


async def send_templated(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    template_key: str,
    to: str,
    context: dict,
    category: str = EmailCategory.NOTIFICATIONS,
) -> bool:
    """Render a catalog template for an org and send it.

    Returns False rather than raising when rendering or delivery fails: mail is
    a side effect of the workflow that triggered it and must never roll back
    the business action itself.
    """
    try:
        rendered = await email_template_service.render(
            db,
            organization_id=organization_id,
            template_key=template_key,
            context={"recipient_name": context.get("recipient_name") or "there", **context},
        )
        sender_name, reply_to = await email_template_service.sender_identity(
            db, organization_id
        )
    except Exception:
        logger.exception("Failed to render email template %s", template_key)
        return False

    return await send_email(
        to,
        rendered.subject,
        rendered.html_body,
        category=category,
        sender_name=sender_name,
        reply_to=reply_to,
    )

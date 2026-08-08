"""Tell the right people that something is waiting on their signature.

The approval gate added to accounts payable, receivable and procurement is only
as good as the notification behind it: a document sitting in "pending" that
nobody is told about is a stalled invoice, not a control. This routes the
request to the people who are actually allowed to approve it, excluding the
person who prepared or submitted it.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import User
from app.services.email_sender import send_templated

logger = logging.getLogger(__name__)

# Roles permitted to approve a finance document.
APPROVER_ROLES = ("admin", "accountant")


async def _approvers(
    db: AsyncSession, organization_id: uuid.UUID | None, exclude_ids: set[uuid.UUID]
) -> list[User]:
    if organization_id is None:
        return []
    users = (
        (
            await db.execute(
                select(User).where(
                    User.organization_id == organization_id,
                    User.is_active.is_(True),
                    User.role.in_(APPROVER_ROLES),
                )
            )
        )
        .scalars()
        .all()
    )
    return [u for u in users if u.id not in exclude_ids]


async def notify_approval_requested(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    document_type: str,
    document_number: str,
    amount: Decimal | str | None,
    counterparty: str,
    prepared_by: User | None,
    review_url: str,
    entity_type: str,
    entity_id: uuid.UUID,
) -> int:
    """Notify eligible approvers in-app and by email. Never raises."""
    exclude = {prepared_by.id} if prepared_by else set()
    try:
        approvers = await _approvers(db, organization_id, exclude)
    except Exception:
        logger.exception("Could not resolve approvers for %s", document_number)
        return 0

    if not approvers:
        return 0

    prepared_name = (
        (prepared_by.display_name or prepared_by.email) if prepared_by else "A colleague"
    )
    for approver in approvers:
        db.add(
            Notification(
                organization_id=organization_id,
                user_id=approver.id,
                kind="approval_requested",
                title=f"Approval needed: {document_type}",
                body=f"{document_number} ({amount}) from {counterparty}.",
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
    try:
        await db.commit()
    except Exception:
        logger.exception("Failed to record approval notifications")
        await db.rollback()

    sent = 0
    for approver in approvers:
        if not approver.email:
            continue
        ok = await send_templated(
            db,
            organization_id=organization_id,
            template_key="approval_request",
            to=approver.email,
            context={
                "recipient_name": approver.display_name or approver.email,
                "document_type": document_type,
                "document_number": document_number,
                "amount": str(amount) if amount is not None else "",
                "counterparty": counterparty,
                "prepared_by": prepared_name,
                "review_url": review_url,
            },
        )
        sent += 1 if ok else 0
    return sent

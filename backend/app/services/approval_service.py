"""Maker-checker enforcement shared by every postable finance document.

Centralising the rules here means accounts payable, accounts receivable, CAM
reconciliation and procurement all behave identically, and an auditor only has
one place to look for the control:

* A document at or above the organization's threshold must be submitted for
  review and then approved before it can post to the general ledger.
* The approver may never be the person who prepared or submitted the document.
* Approving, rejecting and re-opening are recorded with identity and timestamp.

Organizations may disable approvals entirely (``finance_approval_enabled``) or
set a monetary threshold below which documents post directly; in both cases the
document is marked ``not_required`` rather than silently skipping the gate, so
the ledger still shows why no second signature exists.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import POSTABLE_APPROVAL_STATUSES
from app.models.organization import Organization
from app.models.user import User


class ApprovalError(ValueError):
    """Raised when an approval rule is violated."""


async def get_policy(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> tuple[bool, Decimal]:
    """Return ``(enabled, threshold)`` for the organization's approval policy."""
    if organization_id is None:
        return False, Decimal("0")
    org = await db.get(Organization, organization_id)
    if org is None:
        return False, Decimal("0")
    return bool(org.finance_approval_enabled), Decimal(
        str(org.finance_approval_threshold or 0)
    )


async def requires_approval(
    db: AsyncSession, organization_id: uuid.UUID | None, amount: Decimal
) -> tuple[bool, Decimal]:
    """Decide whether ``amount`` must be routed for a second signature."""
    enabled, threshold = await get_policy(db, organization_id)
    if not enabled:
        return False, threshold
    return Decimal(str(amount or 0)) >= threshold, threshold


async def initialize(
    db: AsyncSession,
    document,
    *,
    organization_id: uuid.UUID | None,
    amount: Decimal,
    prepared_by: User,
) -> None:
    """Stamp the maker and reset review state for a new or edited draft."""
    needed, threshold = await requires_approval(db, organization_id, amount)
    if document.prepared_by_id is None:
        document.prepared_by_id = prepared_by.id
    document.approval_status = "pending" if needed else "not_required"
    document.approval_threshold_applied = str(threshold)
    document.submitted_at = None
    document.submitted_by_id = None
    document.approved_at = None
    document.approved_by_id = None
    document.rejected_at = None
    document.rejected_by_id = None
    document.rejection_reason = None


async def submit(
    db: AsyncSession,
    document,
    *,
    organization_id: uuid.UUID | None,
    amount: Decimal,
    user: User,
) -> None:
    """Send a draft for review. No-op when the policy does not require it."""
    needed, threshold = await requires_approval(db, organization_id, amount)
    document.approval_threshold_applied = str(threshold)
    if not needed:
        document.approval_status = "not_required"
        return
    if document.approval_status == "approved":
        raise ApprovalError("This document has already been approved.")
    document.approval_status = "pending"
    document.submitted_at = datetime.now(timezone.utc)
    document.submitted_by_id = user.id
    document.rejected_at = None
    document.rejected_by_id = None
    document.rejection_reason = None


def approve(document, *, user: User) -> None:
    """Approve a pending document, enforcing separation of duties."""
    if document.approval_status == "approved":
        raise ApprovalError("This document has already been approved.")
    if document.approval_status == "not_required":
        raise ApprovalError("This document does not require approval.")
    if document.approval_status != "pending":
        raise ApprovalError("Only a document awaiting review can be approved.")
    _assert_different_person(document, user)
    document.approval_status = "approved"
    document.approved_at = datetime.now(timezone.utc)
    document.approved_by_id = user.id
    document.rejected_at = None
    document.rejected_by_id = None
    document.rejection_reason = None


def reject(document, *, user: User, reason: str | None = None) -> None:
    """Send a pending document back to its preparer for rework."""
    if document.approval_status != "pending":
        raise ApprovalError("Only a document awaiting review can be rejected.")
    _assert_different_person(document, user)
    document.approval_status = "rejected"
    document.rejected_at = datetime.now(timezone.utc)
    document.rejected_by_id = user.id
    document.rejection_reason = reason
    document.approved_at = None
    document.approved_by_id = None


def assert_postable(document, *, user: User | None = None) -> None:
    """Guard called immediately before a document posts to the ledger."""
    if document.approval_status not in POSTABLE_APPROVAL_STATUSES:
        if document.approval_status == "rejected":
            raise ApprovalError(
                "This document was rejected and must be corrected and resubmitted."
            )
        raise ApprovalError(
            "This document must be approved by a second reviewer before it can post."
        )
    # Belt and braces: even an 'approved' record must not have been signed off
    # by its own preparer, in case the row was written by an older code path.
    if document.approval_status == "approved":
        _assert_different_person(document, None, approver_id=document.approved_by_id)


def _assert_different_person(document, user: User | None, approver_id=None) -> None:
    """Reject self-approval by the preparer or the submitter."""
    actor_id = approver_id if user is None else user.id
    if actor_id is None:
        return
    if document.prepared_by_id and actor_id == document.prepared_by_id:
        raise ApprovalError(
            "Separation of duties: the preparer of a document cannot approve it."
        )
    if document.submitted_by_id and actor_id == document.submitted_by_id:
        raise ApprovalError(
            "Separation of duties: the submitter of a document cannot approve it."
        )


def serialize(document) -> dict:
    """Approval fields shaped for an API response."""
    return {
        "approval_status": document.approval_status,
        "prepared_by_id": document.prepared_by_id,
        "submitted_at": document.submitted_at,
        "submitted_by_id": document.submitted_by_id,
        "approved_at": document.approved_at,
        "approved_by_id": document.approved_by_id,
        "rejected_at": document.rejected_at,
        "rejected_by_id": document.rejected_by_id,
        "rejection_reason": document.rejection_reason,
    }

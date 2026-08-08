"""Shared maker-checker (separation of duties) approval state.

Finance documents that post to the audit-grade general ledger — vendor bills,
customer invoices, CAM reconciliations, purchase requisitions and purchase
orders — all move through the same control gate::

    draft -> submitted (pending) -> approved -> posted
                                 -> rejected -> back to draft

The mixin below carries that state plus the identities and timestamps auditors
ask for: who prepared the document, who submitted it for review, and who
approved or rejected it. Enforcement (including the rule that a preparer may
never approve their own work) lives in
:mod:`app.services.approval_service` so every module applies it identically.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

# ``not_required`` is used when an org has approvals disabled or the amount is
# under the configured threshold, so the document can post without a checker.
APPROVAL_STATUSES = ("not_required", "pending", "approved", "rejected")

# States from which a document is allowed to post to the general ledger.
POSTABLE_APPROVAL_STATUSES = ("not_required", "approved")


class ApprovalMixin:
    """Maker-checker columns shared by every postable finance document."""

    approval_status: Mapped[str] = mapped_column(
        String(20), default="not_required", nullable=False
    )

    # The maker: whoever created the document.
    prepared_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # The checker: must be a different person than the maker.
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Snapshot of the threshold that applied when the document was routed, so a
    # later policy change cannot rewrite the history of why review was required.
    approval_threshold_applied: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )

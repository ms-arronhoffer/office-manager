"""Support request model.

A lightweight in-app help channel. Any authenticated user can submit a
``SupportRequest`` (subject + message). The entry is stored, org-scoped, and
surfaced on the Administration → Support Requests page where an admin can review
it and forward it to the address configured to receive support requests
(``SiteSettings.support_email``).
"""
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Lifecycle statuses for a support request.
SUPPORT_REQUEST_STATUSES = ("open", "resolved")


class SupportRequest(TimestampMixin, Base):
    __tablename__ = "support_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )

    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")

    # Who submitted the request. ``requester_user_id`` links to the submitting
    # user when available; name/email are snapshotted so the entry stays
    # readable even if the user is later removed.
    requester_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requester_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requester_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

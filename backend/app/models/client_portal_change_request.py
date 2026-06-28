import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Lifecycle states for a client-submitted profile change request.
CHANGE_REQUEST_STATUSES = ("pending", "approved", "rejected")


class ClientPortalChangeRequest(TimestampMixin, Base):
    """A profile-correction request submitted by an external client portal user.

    The portal profile is intentionally read-only (admin-owned). Rather than let
    external parties edit their own record, they submit a *change request* with
    proposed field values. Internal staff review it and either approve (applying
    the changes to the underlying entity) or reject it.
    """

    __tablename__ = "client_portal_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("client_portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    # Proposed field -> new value mapping (only whitelisted, editable fields).
    proposed_changes: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Optional free-text note from the client explaining the request.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Review metadata.
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    account: Mapped["ClientPortalAccount"] = relationship()

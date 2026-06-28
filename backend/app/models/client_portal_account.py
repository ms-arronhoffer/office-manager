import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Entity types that can be granted a self-service client portal.
CLIENT_PORTAL_ENTITY_TYPES = ("landlord", "management_company")


class ClientPortalAccount(TimestampMixin, Base):
    """Self-service portal access for an external landlord or management company.

    The lifecycle has two tokens:

    * ``signup_token`` — a single-use invite minted by an internal admin/editor.
      The external party redeems it once to activate their portal; redeeming it
      clears the token and stamps ``activated_at``.
    * ``portal_token`` — the persistent credential issued on activation. The
      party uses it to manage their secondary contacts (read-only on the rest of
      the profile) and upload documents.

    One account per (entity_type, entity_id).
    """

    __tablename__ = "client_portal_accounts"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_client_portal_entity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    # One-time invite token.
    signup_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    signup_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Persistent portal credential issued on activation.
    portal_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    portal_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Last time the portal credential was successfully used (sliding-window
    # activity tracking for the internal "portal status" view).
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When set, the portal credential has been revoked by an internal admin and
    # can no longer be used even if it has not yet expired.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

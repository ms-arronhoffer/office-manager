"""Resident communications / announcements model (Phase 2.2).

Mass-communication to residents alongside the existing per-user email and
in-app notification channels. An :class:`Announcement` is composed once by staff
and fanned out to a resident audience over one or more delivery channels
(in-portal, email, SMS). Individual deliveries are recorded as
:class:`AnnouncementRecipient` rows for an auditable send log and so a resident
can see the announcements addressed to them in the portal.

Channels are stored as a comma-separated string to avoid a dialect-specific
array type; helpers convert to/from a list.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Delivery channels an announcement can target.
ANNOUNCEMENT_CHANNELS = ("portal", "email", "sms")

# Announcement lifecycle.
ANNOUNCEMENT_STATUSES = ("draft", "sent")


class Announcement(TimestampMixin, Base):
    """A mass communication authored by staff and sent to a resident audience."""

    __tablename__ = "announcements"
    __table_args__ = (
        Index("idx_announcements_org", "organization_id"),
        Index("idx_announcements_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Comma-separated subset of ANNOUNCEMENT_CHANNELS.
    channels: Mapped[str] = mapped_column(String(100), default="portal", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False, server_default="draft"
    )
    # Optional audience scoping: a single property and/or a resident status.
    audience_office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id", ondelete="SET NULL"), nullable=True
    )
    audience_resident_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    recipients: Mapped[list["AnnouncementRecipient"]] = relationship(
        back_populates="announcement",
        cascade="all, delete-orphan",
    )

    def channel_list(self) -> list[str]:
        return [c for c in (self.channels or "").split(",") if c]


class AnnouncementRecipient(TimestampMixin, Base):
    """A single resident's delivery record for an announcement (send log)."""

    __tablename__ = "announcement_recipients"
    __table_args__ = (
        Index("idx_announcement_recipients_ann", "announcement_id"),
        Index("idx_announcement_recipients_resident", "resident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False
    )
    resident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE"), nullable=False
    )
    # Per-channel delivery outcome flags (best-effort; a channel with no address
    # or an unconfigured transport is simply not delivered).
    emailed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    texted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # In-portal read receipt.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    announcement: Mapped["Announcement"] = relationship(back_populates="recipients")
    resident: Mapped["Resident"] = relationship()


from app.models.resident import Resident  # noqa: E402

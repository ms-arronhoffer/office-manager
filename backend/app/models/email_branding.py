"""Organization-controlled email branding and per-message template overrides.

Every operational email the product sends is currently composed from a built-in
subject line and an on-disk Jinja template. That is fine for a single-tenant
tool, but a customer who puts this in front of their own landlords, residents
and vendors needs the mail to look like it came from *them*.

Two models cover that:

* :class:`EmailBranding` — one row per organization holding the wrapper applied
  to every outgoing message: sender name, reply-to, logo, colours, footer and
  signature.
* :class:`EmailTemplate` — an optional per-organization override of a single
  message type (``template_key``). When no row exists, or the row is inactive,
  the built-in default is used, so an org only owns the messages it has
  deliberately customised.

Bodies are rendered with the same ``{{merge_field}}`` substitution already used
by waivers and lease documents rather than raw Jinja, so a non-technical admin
cannot break a send by writing invalid template syntax.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Fallback palette matching the built-in templates, so an org that saves
# branding without picking colours looks exactly as it did before.
DEFAULT_HEADER_COLOR = "#232f3e"
DEFAULT_ACCENT_COLOR = "#0972d3"


class EmailBranding(TimestampMixin, Base):
    """The wrapper applied to every email an organization sends."""

    __tablename__ = "email_branding"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_email_branding_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )

    # Display name shown in the recipient's inbox, e.g. "Acme Property Care".
    sender_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Where replies go. Left unset, recipients reply to the no-reply mailbox,
    # which is the single most common complaint about automated property mail.
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    header_color: Mapped[str] = mapped_column(
        String(9), default=DEFAULT_HEADER_COLOR, nullable=False
    )
    accent_color: Mapped[str] = mapped_column(
        String(9), default=DEFAULT_ACCENT_COLOR, nullable=False
    )

    # Appended above the legal footer; typically a team name and phone number.
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Postal address, which bulk senders are generally required to include.
    postal_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EmailTemplate(TimestampMixin, Base):
    """An organization's override of one built-in message type."""

    __tablename__ = "email_templates"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "template_key", name="uq_email_template_org_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # One of the keys in app.services.email_catalog.TEMPLATE_CATALOG.
    template_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    subject_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Inactive keeps a customisation on file while reverting to the built-in
    # copy, which is safer than deleting work an admin spent time on.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

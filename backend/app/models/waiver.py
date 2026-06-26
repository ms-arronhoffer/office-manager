"""Digital waiver models.

A small e-signature subsystem that lets an organization send a waiver — built
from a prebuilt or custom template — to any contact, or to an ad-hoc *visitor*
email address. The recipient reviews the rendered document and signs it.

Three tables:

* :class:`WaiverTemplate` — reusable, org-scoped (prebuilt templates are seeded
  per org with ``is_prebuilt=True``). Bodies may contain ``{{merge_field}}``
  placeholders.
* :class:`WaiverRequest` — one send of a template to a recipient. At send time
  the body is rendered and snapshotted (``rendered_body``) and hashed
  (``document_hash``) so the exact signed document is tamper-evident. Access for
  the recipient is via a unique ``sign_token``.
* :class:`WaiverSignature` — the captured signature plus the ESIGN/UETA audit
  trail (intent, consent, attribution, timestamp, IP, user-agent, document
  hash). One signature per request; the request is locked once signed.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Recipient categories for a waiver request.
WAIVER_RECIPIENT_TYPES = ("contact", "visitor")

# Lifecycle statuses for a waiver request.
WAIVER_STATUSES = ("sent", "viewed", "signed", "declined", "expired")

# Signature capture methods.
WAIVER_SIGNATURE_TYPES = ("typed", "drawn")


class WaiverTemplate(TimestampMixin, Base):
    __tablename__ = "waiver_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Prebuilt (seeded) templates vs. custom ones authored by the org.
    is_prebuilt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prebuilt_key: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WaiverRequest(TimestampMixin, Base):
    __tablename__ = "waiver_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("waiver_templates.id", ondelete="SET NULL"), nullable=True
    )

    # Recipient: an existing contact, or a free-form visitor email.
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Optional link back to an EntityContact when recipient_type == 'contact'.
    entity_contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Details the visitor fills in on the signing page (free-form key/value).
    visitor_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Title + immutable snapshot of the exact document rendered at send time.
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rendered_body: Mapped[str] = mapped_column(Text, nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")
    sign_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signature: Mapped["WaiverSignature | None"] = relationship(
        back_populates="request", uselist=False, cascade="all, delete-orphan"
    )


class WaiverSignature(TimestampMixin, Base):
    __tablename__ = "waiver_signatures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("waiver_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    signer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    signature_type: Mapped[str] = mapped_column(String(20), nullable=False, default="typed")
    # Typed: the typed legal name. Drawn: a base64-encoded PNG data URL.
    signature_data: Mapped[str] = mapped_column(Text, nullable=False)

    # ESIGN/UETA evidentiary fields.
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_agreed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Hash of the document the signer agreed to (matches request.document_hash).
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    request: Mapped["WaiverRequest"] = relationship(back_populates="signature")

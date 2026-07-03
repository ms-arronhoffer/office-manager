"""Leasing funnel models (Phase 2.4).

The top-of-funnel that feeds the Phase 2.1 resident/lease domain:

* :class:`RentalApplication` — an online application a prospect submits against a
  vacant :class:`~app.models.resident.RentalUnit`. Moves through a review
  workflow and can be converted into a :class:`~app.models.resident.Resident`.
* :class:`ScreeningReport`   — the result of tenant screening (credit/criminal/
  eviction) obtained from a third-party provider, attached to an application.
* :class:`LeaseSignatureRequest` / :class:`LeaseSignatureParty` — full-lease
  e-signing that extends the waiver/e-signature engine to multi-party lease
  documents. The request snapshots and hashes the rendered lease; each party
  signs via an unguessable per-party token with the same ESIGN/UETA audit trail
  used for waivers. The request completes once every party has signed.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

# Application review lifecycle.
APPLICATION_STATUSES = (
    "submitted", "screening", "approved", "denied", "withdrawn", "converted",
)

# Screening lifecycle + recommendation.
SCREENING_STATUSES = ("pending", "completed", "error")
SCREENING_RECOMMENDATIONS = ("accept", "review", "decline", "unknown")

# Lease e-sign request lifecycle.
LEASE_SIGN_STATUSES = (
    "sent", "partially_signed", "completed", "declined", "expired", "voided",
)
# Per-party lifecycle.
LEASE_PARTY_STATUSES = ("pending", "viewed", "signed", "declined")
# Roles a signing party can play on a lease.
LEASE_PARTY_ROLES = ("tenant", "cosigner", "guarantor", "landlord")
# Signature capture methods (mirrors waivers).
LEASE_SIGNATURE_TYPES = ("typed", "drawn")


class RentalApplication(SoftDeleteMixin, TimestampMixin, Base):
    """An online rental application submitted by a prospect for a unit."""

    __tablename__ = "rental_applications"
    __table_args__ = (
        Index("idx_rental_applications_unit", "unit_id"),
        Index("idx_rental_applications_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rental_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    applicant_first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    applicant_last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    applicant_email: Mapped[str] = mapped_column(String(320), nullable=False)
    applicant_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    desired_move_in: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_income: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Free-form extra fields captured on the application form.
    application_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="submitted", nullable=False, server_default="submitted"
    )
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Set once the application is converted into a resident record.
    resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="SET NULL"), nullable=True
    )

    unit: Mapped["RentalUnit | None"] = relationship("RentalUnit")
    screening_reports: Mapped[list["ScreeningReport"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ScreeningReport(TimestampMixin, Base):
    """A tenant-screening result attached to a rental application."""

    __tablename__ = "screening_reports"
    __table_args__ = (Index("idx_screening_reports_application", "application_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rental_applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, server_default="pending"
    )
    recommendation: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False, server_default="unknown"
    )
    credit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    application: Mapped["RentalApplication"] = relationship(
        back_populates="screening_reports"
    )


class LeaseSignatureRequest(TimestampMixin, Base):
    """A full-lease e-signing envelope, extending the waiver e-signature engine."""

    __tablename__ = "lease_signature_requests"
    __table_args__ = (
        Index("idx_lease_sign_requests_lease", "resident_lease_id"),
        Index("idx_lease_sign_requests_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    resident_lease_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resident_leases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Immutable snapshot + hash of the exact lease document sent for signing.
    rendered_body: Mapped[str] = mapped_column(Text, nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="sent", nullable=False, server_default="sent"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    parties: Mapped[list["LeaseSignatureParty"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="LeaseSignatureParty.sign_order",
    )


class LeaseSignatureParty(TimestampMixin, Base):
    """One signing party on a :class:`LeaseSignatureRequest`."""

    __tablename__ = "lease_signature_parties"
    __table_args__ = (
        Index("idx_lease_sign_parties_request", "request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lease_signature_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    signer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), default="tenant", nullable=False, server_default="tenant"
    )
    sign_order: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    sign_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, server_default="pending"
    )

    signature_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    signature_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ESIGN/UETA evidentiary fields, mirroring WaiverSignature.
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_agreed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    request: Mapped["LeaseSignatureRequest"] = relationship(back_populates="parties")


# Resolved at runtime by SQLAlchemy to avoid a circular import.
from app.models.resident import RentalUnit  # noqa: E402,F401

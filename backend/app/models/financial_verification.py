"""Consent-gated Plaid verification records for rental applicants."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


FINANCIAL_VERIFICATION_STATUSES = (
    "invited", "viewed", "consented", "linking", "processing", "completed",
    "action_required", "declined", "expired", "error", "revoked",
)


class ApplicantFinancialVerification(TimestampMixin, Base):
    __tablename__ = "applicant_financial_verifications"
    __table_args__ = (
        Index("ix_applicant_financial_verifications_item_id", "item_id"),
        Index("ix_applicant_financial_verifications_application", "application_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rental_applications.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="invited", server_default="invited", nullable=False)
    invitation_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_text: Mapped[str | None] = mapped_column(Text)
    consent_version: Mapped[str | None] = mapped_column(String(40))
    consent_ip: Mapped[str | None] = mapped_column(String(64))
    consent_user_agent: Mapped[str | None] = mapped_column(String(500))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    item_id: Mapped[str | None] = mapped_column(String(100))
    institution_name: Mapped[str | None] = mapped_column(String(255))
    account_count: Mapped[int | None] = mapped_column(Integer)
    summary_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    identity_match: Mapped[bool | None] = mapped_column(Boolean)
    ownership_match: Mapped[bool | None] = mapped_column(Boolean)
    available_balance_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    current_balance_total: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    recurring_income_monthly: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    income_months_observed: Mapped[int | None] = mapped_column(Integer)
    recommendation: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped["RentalApplication"] = relationship(back_populates="financial_verifications")


class FinancialVerificationWebhookEvent(TimestampMixin, Base):
    __tablename__ = "financial_verification_webhook_events"
    __table_args__ = (UniqueConstraint("event_digest", name="uq_financial_verification_webhook_digest"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applicant_financial_verifications.id", ondelete="CASCADE"), nullable=False, index=True)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    webhook_type: Mapped[str] = mapped_column(String(50), nullable=False)
    webhook_code: Mapped[str] = mapped_column(String(80), nullable=False)


from app.models.leasing_funnel import RentalApplication  # noqa: E402,F401
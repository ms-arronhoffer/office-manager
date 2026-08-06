"""Encrypted organization-scoped configuration for tenant integration providers."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


INTEGRATION_CONFIG_PROVIDERS = ("resident_payments", "screening", "plaid")


class OrganizationIntegrationConfig(TimestampMixin, Base):
    __tablename__ = "organization_integration_configs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "provider", name="uq_org_integration_config_org_provider"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings_json: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verify_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_verify_error: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
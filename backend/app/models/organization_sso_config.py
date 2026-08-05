"""Per-organization OIDC single sign-on configuration and login state.

Two tables back the SSO feature:

  - ``organization_sso_configs`` — one IdP connection per organization. The
    client secret is encrypted at rest (see app.utils.crypto), matching the
    Buildium connector and platform Stripe config conventions.
  - ``sso_login_states`` — short-lived, single-use authorization-request state.
    Persisting rather than cookie-storing the ``state``/PKCE verifier/nonce
    triple keeps the callback correct across multiple API workers and makes
    single-use enforcement a database constraint rather than a client promise.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

SSO_PROVIDERS = ("oidc",)

# Roles an SSO-provisioned account may be created with.
SSO_PROVISION_ROLES = ("viewer", "editor", "accountant", "admin")


class OrganizationSsoConfig(TimestampMixin, Base):
    """OIDC identity-provider connection for a single organization."""

    __tablename__ = "organization_sso_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_sso_config_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(20), default="oidc", nullable=False)
    # Issuer identifier, e.g. https://login.microsoftonline.com/<tenant>/v2.0.
    # Discovery, JWKS lookup, and the ID token ``iss`` check all derive from it.
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Encrypted at rest — see app.utils.crypto.encrypt_secret/decrypt_secret.
    # Never returned to the client; only a masked hint is exposed.
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # Lowercase bare domains ("contoso.com"). A verified IdP email must match
    # one of these before a user is matched or provisioned.
    allowed_email_domains: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
    # When true, password login is refused for users in this organization.
    enforce_sso: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Role granted to accounts provisioned on first SSO login.
    default_role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SsoLoginState(Base):
    """One pending authorization request. Single-use and short-lived."""

    __tablename__ = "sso_login_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

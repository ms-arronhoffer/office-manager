"""Organization single sign-on (OIDC authorization code + PKCE).

Public endpoints drive the login flow:

  ``GET /api/v1/sso/lookup``                 discover whether SSO is available
  ``GET /api/v1/sso/{org_slug}/authorize``   start the flow, redirect to the IdP
  ``GET /api/v1/sso/callback``               finish the flow, issue the app JWT

Admin endpoints manage the org's IdP connection and are gated on the ``sso``
entitlement plus the admin role.

Tokens, authorization codes, and the client secret are never logged.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_feature, require_role
from app.auth.jwt_handler import create_access_token
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.organization_sso_config import (
    SSO_PROVISION_ROLES,
    OrganizationSsoConfig,
    SsoLoginState,
)
from app.models.user import User
from app.services import entitlements as ent
from app.services import sso_service
from app.services.console_roles import resolve_console_role
from app.services.sso_service import SsoError
from app.utils.crypto import decrypt_secret, encrypt_secret, mask_secret

logger = logging.getLogger(__name__)

router = APIRouter()

# How long an unconsumed authorization request stays valid.
_STATE_TTL_MINUTES = 10

_MFA_CHALLENGE_MINUTES = 15


# ── Schemas ───────────────────────────────────────────────────────────────────

class SsoLookupResponse(BaseModel):
    enabled: bool
    organization_slug: str | None = None
    organization_name: str | None = None
    authorize_url: str | None = None
    enforce_sso: bool = False


class SsoConfigOut(BaseModel):
    configured: bool
    provider: str | None = None
    issuer: str | None = None
    client_id: str | None = None
    client_secret_hint: str | None = None
    allowed_email_domains: list[str] = Field(default_factory=list)
    enforce_sso: bool = False
    is_enabled: bool = False
    default_role: str = "viewer"
    last_login_at: datetime | None = None
    redirect_uri: str | None = None
    login_url: str | None = None


class SsoConfigIn(BaseModel):
    issuer: str
    client_id: str
    # Optional on update: omitting it keeps the stored secret unchanged.
    client_secret: str | None = None
    allowed_email_domains: list[str]
    enforce_sso: bool = False
    is_enabled: bool = True
    default_role: str = "viewer"

    @field_validator("issuer")
    @classmethod
    def _validate_issuer(cls, value: str) -> str:
        try:
            return sso_service.normalize_issuer(value)
        except SsoError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("client_id")
    @classmethod
    def _validate_client_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Client ID is required.")
        return value.strip()

    @field_validator("allowed_email_domains")
    @classmethod
    def _validate_domains(cls, value: list[str]) -> list[str]:
        domains = sso_service.normalize_domains(value)
        if not domains:
            raise ValueError("At least one allowed email domain is required.")
        for domain in domains:
            if "." not in domain or "@" in domain or "/" in domain:
                raise ValueError(f"'{domain}' is not a valid email domain.")
        return domains

    @field_validator("default_role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        if value not in SSO_PROVISION_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(SSO_PROVISION_ROLES)}")
        return value


# ── Helpers ───────────────────────────────────────────────────────────────────

def _callback_url() -> str:
    return settings.SSO_CALLBACK_URL


def _encrypt_client_secret(secret: str) -> str:
    """Encrypt an SSO secret or return an actionable deployment error."""
    try:
        return encrypt_secret(secret)
    except RuntimeError as exc:
        logger.error("SSO secret encryption is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "SSO secret storage is unavailable. Configure a valid "
                "ENCRYPTION_KEY on the backend and restart it."
            ),
        ) from exc


def _login_redirect(**params: str) -> RedirectResponse:
    """Bounce back to the SPA login page.

    Results travel in the URL fragment so tokens never reach a server access log
    or the ``Referer`` header of a subsequent request.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(url=f"{base}/login#{urlencode(params)}", status_code=status.HTTP_302_FOUND)


def _error_redirect(code: str) -> RedirectResponse:
    return _login_redirect(sso_error=code)


async def _load_enabled_config(
    db: AsyncSession, org: Organization
) -> OrganizationSsoConfig | None:
    """Return the org's SSO config when SSO is usable, else ``None``."""
    if not org.is_active or not ent.has_feature(org, "sso"):
        return None
    if ent.is_access_blocked(ent.org_access_state(org)):
        return None
    config = (
        await db.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == org.id
            )
        )
    ).scalar_one_or_none()
    if config is None or not config.is_enabled:
        return None
    return config


async def _org_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    return (
        await db.execute(select(Organization).where(Organization.slug == slug.strip().lower()))
    ).scalar_one_or_none()


async def _require_org(db: AsyncSession, user: User) -> Organization:
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not attached to an organization.",
        )
    org = (
        await db.execute(select(Organization).where(Organization.id == user.organization_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


def _config_out(config: OrganizationSsoConfig | None, org: Organization | None) -> SsoConfigOut:
    login_url = None
    if org is not None:
        login_url = f"{settings.FRONTEND_URL.rstrip('/')}/login#{urlencode({'sso_org': org.slug})}"
    if config is None:
        return SsoConfigOut(configured=False, redirect_uri=_callback_url(), login_url=login_url)
    return SsoConfigOut(
        configured=True,
        provider=config.provider,
        issuer=config.issuer,
        client_id=config.client_id,
        client_secret_hint=mask_secret(decrypt_secret(config.client_secret_encrypted)),
        allowed_email_domains=list(config.allowed_email_domains or []),
        enforce_sso=config.enforce_sso,
        is_enabled=config.is_enabled,
        default_role=config.default_role,
        last_login_at=config.last_login_at,
        redirect_uri=_callback_url(),
        login_url=login_url,
    )


async def _resolve_user(
    db: AsyncSession,
    org: Organization,
    config: OrganizationSsoConfig,
    email: str,
    first_name: str,
) -> User:
    """Match or provision the organization member behind a verified SSO email."""
    if not sso_service.is_domain_allowed(email, list(config.allowed_email_domains or [])):
        raise SsoError(
            "Email domain is not allowed for this organization.",
            code="domain_not_allowed",
        )

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is not None:
        # An existing account anywhere else in the system must never be pulled
        # into this organization by an SSO login.
        if user.organization_id != org.id:
            raise SsoError(
                "Account belongs to a different organization.",
                code="account_conflict",
            )
        if not user.is_active:
            raise SsoError("Account is inactive.", code="account_inactive")
        if user.auth_provider != "sso":
            user.auth_provider = "sso"
        user.email_verified = True
        user.display_name = first_name
        return user

    seat_limit = ent.get_limit(org, "max_seats")
    if seat_limit is not None:
        seat_count = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.organization_id == org.id, User.is_active.is_(True))
            )
        ).scalar_one()
        if seat_count >= seat_limit:
            raise SsoError("Organization seat limit reached.", code="seat_limit")

    user = User(
        email=email,
        display_name=first_name,
        organization_id=org.id,
        auth_provider="sso",
        role=config.default_role,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    return user


# ── Public flow ───────────────────────────────────────────────────────────────

@router.get("/lookup", response_model=SsoLookupResponse)
async def lookup(
    slug: str | None = Query(default=None, max_length=100),
    email: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
):
    """Resolve an org slug or email domain to an SSO start URL."""
    org: Organization | None = None
    if slug:
        org = await _org_by_slug(db, slug)
    elif email and "@" in email:
        domain = sso_service.email_domain(email)
        candidates = (
            await db.execute(
                select(OrganizationSsoConfig, Organization)
                .join(Organization, Organization.id == OrganizationSsoConfig.organization_id)
                .where(OrganizationSsoConfig.is_enabled.is_(True))
            )
        ).all()
        for config, candidate_org in candidates:
            if domain in sso_service.normalize_domains(list(config.allowed_email_domains or [])):
                org = candidate_org
                break

    if org is None:
        return SsoLookupResponse(enabled=False)

    config = await _load_enabled_config(db, org)
    if config is None:
        return SsoLookupResponse(enabled=False)

    return SsoLookupResponse(
        enabled=True,
        organization_slug=org.slug,
        organization_name=org.name,
        authorize_url=f"/api/v1/sso/{org.slug}/authorize",
        enforce_sso=config.enforce_sso,
    )


@router.get("/{org_slug}/authorize")
async def authorize(org_slug: str, db: AsyncSession = Depends(get_db)):
    """Begin the OIDC flow and redirect the browser to the identity provider."""
    org = await _org_by_slug(db, org_slug)
    if org is None:
        return _error_redirect("not_configured")
    config = await _load_enabled_config(db, org)
    if config is None:
        return _error_redirect("not_configured")

    try:
        document = await sso_service.discover(config.issuer)
    except SsoError as exc:
        logger.warning("SSO discovery failed for org %s: %s", org.id, exc)
        return _error_redirect("provider_unavailable")
    except Exception:
        logger.exception("Unexpected SSO authorize failure for org %s", org.id)
        return _error_redirect("internal_error")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = sso_service.generate_pkce()
    redirect_uri = _callback_url()

    now = datetime.now(timezone.utc)
    db.add(
        SsoLoginState(
            state=state,
            organization_id=org.id,
            code_verifier=verifier,
            nonce=nonce,
            redirect_uri=redirect_uri,
            expires_at=now + timedelta(minutes=_STATE_TTL_MINUTES),
            created_at=now,
        )
    )
    # Opportunistic cleanup keeps the table from growing without a cron job.
    await db.execute(
        SsoLoginState.__table__.delete().where(
            SsoLoginState.expires_at < now - timedelta(hours=1)
        )
    )
    await db.commit()

    return RedirectResponse(
        url=sso_service.build_authorize_url(
            document["authorization_endpoint"],
            client_id=config.client_id,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=challenge,
        ),
        status_code=status.HTTP_302_FOUND,
    )


async def _callback_impl(
    *, state: str, code: str, error: str | None, db: AsyncSession
):
    """Complete the OIDC flow and hand the SPA an application JWT."""
    if error:
        logger.info("SSO callback returned provider error")
        return _error_redirect("provider_error")
    if not state or not code:
        return _error_redirect("invalid_request")

    now = datetime.now(timezone.utc)
    login_state = (
        await db.execute(select(SsoLoginState).where(SsoLoginState.state == state))
    ).scalar_one_or_none()

    # Unknown, already-used, and expired states are all rejected identically.
    if login_state is None or login_state.consumed_at is not None:
        return _error_redirect("invalid_state")
    expires_at = login_state.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        return _error_redirect("expired_state")

    # Burn the state before any network call so a replay cannot race this one.
    login_state.consumed_at = now
    await db.commit()

    org = (
        await db.execute(
            select(Organization).where(Organization.id == login_state.organization_id)
        )
    ).scalar_one_or_none()
    if org is None:
        return _error_redirect("invalid_state")
    config = await _load_enabled_config(db, org)
    if config is None:
        return _error_redirect("sso_disabled")

    try:
        client_secret = decrypt_secret(config.client_secret_encrypted)
    except ValueError as exc:
        logger.error("SSO client secret could not be decrypted for org %s: %s", org.id, exc)
        return _error_redirect("configuration_error")

    try:
        document = await sso_service.discover(config.issuer)
        tokens = await sso_service.exchange_code(
            document["token_endpoint"],
            code=code,
            client_id=config.client_id,
            client_secret=client_secret,
            redirect_uri=login_state.redirect_uri,
            code_verifier=login_state.code_verifier,
        )
        jwks = await sso_service.fetch_jwks(document["jwks_uri"])
        claims = sso_service.verify_id_token(
            tokens["id_token"],
            jwks=jwks,
            issuer=config.issuer,
            client_id=config.client_id,
            nonce=login_state.nonce,
        )
        email = sso_service.extract_verified_email(claims)
        first_name = sso_service.extract_first_name(claims, email)
        user = await _resolve_user(db, org, config, email, first_name)
    except SsoError as exc:
        await db.rollback()
        logger.warning("SSO callback rejected for org %s: %s", org.id, exc)
        return _error_redirect(exc.code)
    except ValueError as exc:
        await db.rollback()
        logger.error("SSO configuration could not be decrypted for org %s: %s", org.id, exc)
        return _error_redirect("configuration_error")
    except Exception:
        await db.rollback()
        logger.exception("Unexpected SSO callback failure for org %s", org.id)
        return _error_redirect("internal_error")

    user.last_login_at = now
    config.last_login_at = now
    await db.commit()
    await db.refresh(user)

    # Mirror the password and Google flows: an account with TOTP enrolled still
    # completes its second factor before receiving a session token.
    if user.totp_enabled:
        challenge = secrets.token_hex(32)
        user.mfa_challenge_token = challenge
        user.mfa_challenge_expires_at = now + timedelta(minutes=_MFA_CHALLENGE_MINUTES)
        await db.commit()
        return _login_redirect(sso_mfa=challenge)

    console_role = await resolve_console_role(db, user)
    token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role,
            "org_id": str(user.organization_id) if user.organization_id else None,
            "is_super_admin": user.is_super_admin,
            "console_role": console_role,
        }
    )
    return _login_redirect(sso_token=token)


@router.get("/callback")
async def callback(
    state: str = Query(default="", max_length=256),
    code: str = Query(default="", max_length=4096),
    error: str | None = Query(default=None, max_length=256),
    db: AsyncSession = Depends(get_db),
):
    """Complete SSO without ever exposing an unbranded framework error page."""
    try:
        return await _callback_impl(state=state, code=code, error=error, db=db)
    except Exception:
        await db.rollback()
        logger.exception("Unhandled SSO callback failure")
        return _error_redirect("internal_error")


# ── Admin configuration ───────────────────────────────────────────────────────

@router.get("/config", response_model=SsoConfigOut)
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    _: User = Depends(require_feature("sso")),
):
    org = await _require_org(db, current_user)
    config = (
        await db.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == org.id
            )
        )
    ).scalar_one_or_none()
    return _config_out(config, org)


@router.put("/config", response_model=SsoConfigOut)
async def save_config(
    payload: SsoConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    _: User = Depends(require_feature("sso")),
):
    org = await _require_org(db, current_user)
    config = (
        await db.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == org.id
            )
        )
    ).scalar_one_or_none()

    if config is None:
        if not payload.client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A client secret is required when first configuring SSO.",
            )
        config = OrganizationSsoConfig(
            id=uuid.uuid4(),
            organization_id=org.id,
            issuer=payload.issuer,
            client_id=payload.client_id,
            client_secret_encrypted=_encrypt_client_secret(payload.client_secret),
        )
        db.add(config)

    config.provider = "oidc"
    config.issuer = payload.issuer
    config.client_id = payload.client_id
    if payload.client_secret:
        config.client_secret_encrypted = _encrypt_client_secret(payload.client_secret)
    config.allowed_email_domains = payload.allowed_email_domains
    config.enforce_sso = payload.enforce_sso
    config.is_enabled = payload.is_enabled
    config.default_role = payload.default_role

    await db.commit()
    await db.refresh(config)
    sso_service.clear_metadata_cache()
    return _config_out(config, org)


@router.delete("/config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    _: User = Depends(require_feature("sso")),
):
    org = await _require_org(db, current_user)
    config = (
        await db.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == org.id
            )
        )
    ).scalar_one_or_none()
    if config is not None:
        await db.delete(config)
        await db.commit()
        sso_service.clear_metadata_cache()

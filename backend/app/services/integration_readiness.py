"""Secret-safe readiness and non-mutating verification for external providers."""
from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.external_sync import BankFeedConnection, QuickBooksConnection
from app.models.organization_sso_config import OrganizationSsoConfig
from app.services import sso_service
from app.services.stripe_settings import get_stripe_config, resolve_stripe_settings


def _mode(*, environment: str = "", key: str = "", url: str = "") -> str:
    value = " ".join((environment, key[:12], url)).lower()
    if any(marker in value for marker in ("sandbox", "test", "development", "localhost")):
        return "sandbox"
    if any(marker in value for marker in ("production", "live", "sk_live_", "pk_live_")):
        return "live"
    return "unknown"


def _item(
    provider: str,
    *,
    scope: str,
    configured: bool,
    verified: bool | None,
    verification_supported: bool,
    mode: str,
    missing_config: list[str],
    last_verified_at: datetime | None = None,
    last_error: str | None = None,
    detail: str | None = None,
) -> dict:
    return {
        "provider": provider,
        "scope": scope,
        "configured": configured,
        "verified": verified,
        "verification_supported": verification_supported,
        "mode": mode,
        "missing_config": missing_config,
        "last_verified_at": last_verified_at,
        "last_error": last_error,
        "detail": detail,
    }


async def get_readiness(db: AsyncSession, organization_id: uuid.UUID) -> list[dict]:
    """Return readiness metadata without returning credentials or provider tokens."""
    stripe = await resolve_stripe_settings(db)
    stripe_row = await get_stripe_config(db)
    stripe_missing = [
        name
        for name, value in (
            ("STRIPE_SECRET_KEY", stripe.secret_key),
            ("STRIPE_WEBHOOK_SECRET", stripe.webhook_secret),
            ("STRIPE_PRICE_ID_PRO", stripe.price_id_pro),
        )
        if not value
    ]

    payment_key = settings.PAYMENTS_API_KEY
    payment_publishable = settings.PAYMENTS_PUBLISHABLE_KEY
    payment_missing = [
        name
        for name, value in (
            ("PAYMENTS_API_KEY", payment_key),
            ("PAYMENTS_PUBLISHABLE_KEY", payment_publishable),
        )
        if not value
    ]

    screening_missing = [
        name
        for name, value in (
            ("SCREENING_API_KEY", settings.SCREENING_API_KEY),
            ("SCREENING_API_URL", settings.SCREENING_API_URL),
        )
        if not value
    ]

    qbo = (
        await db.execute(
            select(QuickBooksConnection).where(
                QuickBooksConnection.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    qbo_missing = [
        name
        for name, value in (
            ("QBO_CLIENT_ID", settings.QBO_CLIENT_ID),
            ("QBO_CLIENT_SECRET", settings.QBO_CLIENT_SECRET),
            ("QBO_REDIRECT_URI", settings.QBO_REDIRECT_URI),
        )
        if not value
    ]

    plaid_connections = (
        await db.execute(
            select(BankFeedConnection).where(
                BankFeedConnection.organization_id == organization_id
            )
        )
    ).scalars().all()
    plaid_missing = [
        name
        for name, value in (
            ("PLAID_CLIENT_ID", settings.PLAID_CLIENT_ID),
            ("PLAID_SECRET", settings.PLAID_SECRET),
        )
        if not value
    ]
    plaid_healthy = [c for c in plaid_connections if c.status == "connected" and c.is_enabled]
    plaid_latest = max(
        (c.last_sync_at or c.updated_at for c in plaid_connections), default=None
    )
    plaid_error = next((c.last_error for c in plaid_connections if c.last_error), None)

    sso = (
        await db.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    sso_missing = []
    if sso is None:
        sso_missing = ["issuer", "client_id", "client_secret", "allowed_email_domains"]

    return [
        _item(
            "platform_stripe",
            scope="platform",
            configured=not stripe_missing,
            verified=stripe_row.last_verify_ok if stripe_row else None,
            verification_supported=True,
            mode=_mode(key=stripe.secret_key),
            missing_config=stripe_missing,
            last_verified_at=stripe_row.last_verified_at if stripe_row else None,
            last_error=stripe_row.last_verify_error if stripe_row else None,
            detail="Platform subscription billing; credentials are managed by platform administrators.",
        ),
        _item(
            "resident_payments",
            scope="organization",
            configured=not payment_missing,
            verified=None,
            verification_supported=(settings.PAYMENTS_PROVIDER or "stripe").lower() == "stripe",
            mode=_mode(key=payment_key, url=settings.PAYMENTS_API_URL),
            missing_config=payment_missing,
            detail="No persisted verification result; run the safe account check.",
        ),
        _item(
            "screening",
            scope="organization",
            configured=not screening_missing,
            verified=None,
            verification_supported=bool(settings.SCREENING_HEALTH_URL),
            mode=_mode(url=settings.SCREENING_API_URL),
            missing_config=screening_missing,
            detail=(
                "Safe verification uses SCREENING_HEALTH_URL. A sandbox report is required when the provider has no non-mutating endpoint."
            ),
        ),
        _item(
            "quickbooks",
            scope="organization",
            configured=not qbo_missing,
            verified=(qbo.status == "connected") if qbo else None,
            verification_supported=False,
            mode=_mode(environment=settings.QBO_ENVIRONMENT, url=settings.QBO_API_BASE_URL),
            missing_config=qbo_missing,
            last_verified_at=(qbo.updated_at if qbo and qbo.status == "connected" else None),
            last_error=qbo.last_error if qbo else None,
            detail="A successful OAuth token exchange establishes the persisted connection.",
        ),
        _item(
            "plaid",
            scope="organization",
            configured=not plaid_missing,
            verified=True if plaid_healthy else (False if plaid_connections else None),
            verification_supported=False,
            mode=_mode(environment=settings.PLAID_ENV, url=settings.PLAID_API_BASE_URL),
            missing_config=plaid_missing,
            last_verified_at=plaid_latest,
            last_error=plaid_error,
            detail="A successful Link token exchange and account lookup establishes a connection.",
        ),
        _item(
            "sso",
            scope="organization",
            configured=sso is not None,
            verified=True if sso and sso.last_login_at else None,
            verification_supported=sso is not None,
            mode=_mode(url=sso.issuer if sso else ""),
            missing_config=sso_missing,
            last_verified_at=sso.last_login_at if sso else None,
            detail="Discovery can be checked safely; a successful login is required for full certification.",
        ),
    ]


async def verify_resident_payments(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> dict:
    provider = (settings.PAYMENTS_PROVIDER or "stripe").lower()
    if provider != "stripe":
        return {"provider": "resident_payments", "ok": False, "verification_supported": False,
                "error": f"Safe verification is not implemented for payment provider '{provider}'."}
    if not settings.PAYMENTS_API_KEY:
        return {"provider": "resident_payments", "ok": False, "verification_supported": True,
                "error": "PAYMENTS_API_KEY is not configured."}
    configured_url = settings.PAYMENTS_API_URL or "https://api.stripe.com/v1/payment_intents"
    parsed = urlparse(configured_url)
    account_url = f"{parsed.scheme}://{parsed.netloc}/v1/account"
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
            response = await client.get(
                account_url, headers={"Authorization": f"Bearer {settings.PAYMENTS_API_KEY}"}
            )
        if response.status_code != 200:
            return {"provider": "resident_payments", "ok": False, "verification_supported": True,
                    "error": f"Stripe account verification returned HTTP {response.status_code}."}
        body = response.json()
        if not isinstance(body, dict) or not str(body.get("id", "")).startswith("acct_"):
            return {"provider": "resident_payments", "ok": False, "verification_supported": True,
                    "error": "Stripe returned an unexpected account response."}
        return {"provider": "resident_payments", "ok": True, "verification_supported": True,
                "error": None}
    except (httpx.HTTPError, ValueError) as exc:
        return {"provider": "resident_payments", "ok": False, "verification_supported": True,
                "error": f"Stripe account verification failed: {exc.__class__.__name__}."}


async def verify_screening(*, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if not settings.SCREENING_HEALTH_URL:
        return {"provider": "screening", "ok": False, "verification_supported": False,
                "error": "No provider-documented non-mutating SCREENING_HEALTH_URL is configured; certify with a sandbox report."}
    if not settings.SCREENING_API_KEY:
        return {"provider": "screening", "ok": False, "verification_supported": True,
                "error": "SCREENING_API_KEY is not configured."}
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
            response = await client.get(
                settings.SCREENING_HEALTH_URL,
                headers={"Authorization": f"Bearer {settings.SCREENING_API_KEY}", "Accept": "application/json"},
            )
        ok = 200 <= response.status_code < 300
        return {"provider": "screening", "ok": ok, "verification_supported": True,
                "error": None if ok else f"Screening health check returned HTTP {response.status_code}."}
    except httpx.HTTPError as exc:
        return {"provider": "screening", "ok": False, "verification_supported": True,
                "error": f"Screening health check failed: {exc.__class__.__name__}."}


async def verify_sso(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    config = (
        await db.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if config is None:
        return {"provider": "sso", "ok": False, "verification_supported": False,
                "error": "SSO is not configured for this organization."}
    try:
        await sso_service.discover(config.issuer)
        return {"provider": "sso", "ok": True, "verification_supported": True, "error": None}
    except sso_service.SsoError as exc:
        return {"provider": "sso", "ok": False, "verification_supported": True,
                "error": str(exc)}
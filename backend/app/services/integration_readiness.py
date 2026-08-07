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
from app.services import organization_integration_settings as org_settings
from app.services.bank_feed.plaid_client import PlaidApiError, PlaidClient


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
    source: str = "tenant",
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
        "source": source,
    }


async def get_readiness(db: AsyncSession, organization_id: uuid.UUID) -> list[dict]:
    """Return readiness metadata without returning credentials or provider tokens."""
    payment = await org_settings.resolve(db, organization_id, "resident_payments")
    payment_row = await org_settings.get_config_row(db, organization_id, "resident_payments")
    screening = await org_settings.resolve(db, organization_id, "screening")
    screening_row = await org_settings.get_config_row(db, organization_id, "screening")
    plaid = await org_settings.resolve(db, organization_id, "plaid")
    plaid_row = await org_settings.get_config_row(db, organization_id, "plaid")
    payment_missing = [
        name
        for name, value in (
            ("secret_api_key", payment.secret_api_key),
            ("publishable_key", payment.publishable_key),
        )
        if not value
    ]

    screening_missing = [
        name
        for name, value in (
            ("api_key", screening.api_key),
            ("api_url", screening.api_url),
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

    plaid_missing = [
        name
        for name, value in (
            ("client_id", plaid.client_id),
            ("secret", plaid.secret),
        )
        if not value
    ]
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
            "resident_payments",
            scope="organization",
            configured=not payment_missing,
            verified=payment_row.last_verify_ok if payment_row else None,
            verification_supported=payment.provider.lower() == "stripe",
            mode=_mode(key=payment.secret_api_key, url=payment.api_url),
            missing_config=payment_missing,
            last_verified_at=payment_row.last_verified_at if payment_row else None,
            last_error=payment_row.last_verify_error if payment_row else None,
            detail="Legacy/platform fallback. Save to tenant before normal operation." if payment.source == "legacy_env" else None,
            source=payment.source,
        ),
        _item(
            "screening",
            scope="organization",
            configured=not screening_missing,
            verified=screening_row.last_verify_ok if screening_row else None,
            verification_supported=bool(screening.health_url),
            mode=_mode(url=screening.api_url),
            missing_config=screening_missing,
            last_verified_at=screening_row.last_verified_at if screening_row else None,
            last_error=screening_row.last_verify_error if screening_row else None,
            detail="Legacy/platform fallback. Save to tenant before normal operation." if screening.source == "legacy_env" else "A sandbox report is required when no health URL exists.",
            source=screening.source,
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
            verified=plaid_row.last_verify_ok if plaid_row else None,
            verification_supported=True,
            mode=_mode(environment=plaid.environment, url=plaid.api_base_url),
            missing_config=plaid_missing,
            last_verified_at=plaid_row.last_verified_at if plaid_row else None,
            last_error=plaid_row.last_verify_error if plaid_row else None,
            detail=(
                "Legacy/platform fallback. Save to tenant before normal operation."
                if plaid.source == "legacy_env"
                else (
                    "Applicant financial verification is enabled. Safe credential verification lists one institution without creating an Item."
                    if plaid.applicant_verification_enabled
                    else "Bank feeds are available. Applicant financial verification is disabled."
                )
            ),
            source=plaid.source,
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
    resolved: org_settings.ResidentPaymentsSettings | None = None,
    *, transport: httpx.AsyncBaseTransport | None = None
) -> dict:
    resolved = resolved or org_settings.legacy_settings("resident_payments")
    if not resolved.is_enabled:
        return {"provider": "resident_payments", "ok": False, "verification_supported": True,
                "error": "Resident payments are disabled for this organization."}
    provider = resolved.provider.lower()
    if provider != "stripe":
        return {"provider": "resident_payments", "ok": False, "verification_supported": False,
                "error": f"Safe verification is not implemented for payment provider '{provider}'."}
    if not resolved.secret_api_key:
        return {"provider": "resident_payments", "ok": False, "verification_supported": True,
                "error": "PAYMENTS_API_KEY is not configured."}
    configured_url = resolved.api_url or "https://api.stripe.com/v1/payment_intents"
    parsed = urlparse(configured_url)
    account_url = f"{parsed.scheme}://{parsed.netloc}/v1/account"
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
            response = await client.get(
                account_url, headers={"Authorization": f"Bearer {resolved.secret_api_key}"}
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


async def verify_screening(
    resolved: org_settings.ScreeningSettings | None = None,
    *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    resolved = resolved or org_settings.legacy_settings("screening")
    if not resolved.is_enabled:
        return {"provider": "screening", "ok": False, "verification_supported": bool(resolved.health_url),
                "error": "Screening is disabled for this organization."}
    if not resolved.health_url:
        return {"provider": "screening", "ok": False, "verification_supported": False,
                "error": "No provider-documented non-mutating SCREENING_HEALTH_URL is configured; certify with a sandbox report."}
    if not resolved.api_key:
        return {"provider": "screening", "ok": False, "verification_supported": True,
                "error": "SCREENING_API_KEY is not configured."}
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
            response = await client.get(
                resolved.health_url,
                headers={"Authorization": f"Bearer {resolved.api_key}", "Accept": "application/json"},
            )
        ok = 200 <= response.status_code < 300
        return {"provider": "screening", "ok": ok, "verification_supported": True,
                "error": None if ok else f"Screening health check returned HTTP {response.status_code}."}
    except httpx.HTTPError as exc:
        return {"provider": "screening", "ok": False, "verification_supported": True,
                "error": f"Screening health check failed: {exc.__class__.__name__}."}


async def verify_plaid(resolved: org_settings.PlaidSettings) -> dict:
    if not resolved.is_enabled:
        return {"provider": "plaid", "ok": False, "verification_supported": True,
                "error": "Plaid is disabled for this organization."}
    if not resolved.client_id or not resolved.secret:
        return {"provider": "plaid", "ok": False, "verification_supported": True,
                "error": "Plaid credentials are not configured."}
    try:
        await PlaidClient(config=resolved).get_institutions(count=1)
        return {"provider": "plaid", "ok": True, "verification_supported": True, "error": None}
    except PlaidApiError as exc:
        return {"provider": "plaid", "ok": False, "verification_supported": True,
                "error": f"Plaid verification failed: {exc}."}


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
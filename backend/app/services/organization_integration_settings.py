"""Validation and resolution of tenant integration settings."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.organization_integration_config import OrganizationIntegrationConfig
from app.utils.crypto import decrypt_secret, mask_secret

Provider = Literal["resident_payments", "screening", "plaid"]
Source = Literal["tenant", "legacy_env", "unconfigured"]
PROVIDERS: tuple[Provider, ...] = ("resident_payments", "screening", "plaid")
PLAID_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


@dataclass(frozen=True)
class ResidentPaymentsSettings:
    provider: str
    secret_api_key: str
    publishable_key: str
    api_url: str
    is_enabled: bool
    source: Source


@dataclass(frozen=True)
class ScreeningSettings:
    provider_name: str
    api_key: str
    api_url: str
    health_url: str
    poll_attempts: int
    poll_interval_seconds: float
    is_enabled: bool
    source: Source


@dataclass(frozen=True)
class PlaidSettings:
    client_id: str
    secret: str
    environment: str
    api_base_url: str
    country_codes: tuple[str, ...]
    redirect_uri: str
    timeout_seconds: int
    is_enabled: bool
    source: Source
    webhook_url: str = ""
    applicant_verification_enabled: bool = False
    applicant_redirect_uri: str = ""


IntegrationSettings = ResidentPaymentsSettings | ScreeningSettings | PlaidSettings


def _https_url(value: str, field: str, *, allow_empty: bool = False) -> str:
    value = value.strip().rstrip("/")
    if not value and allow_empty:
        return ""
    parsed = urlparse(value)
    is_dev = (settings.APP_ENV or "").lower() in {"dev", "development", "local", "test", "testing"}
    if parsed.scheme not in ({"http", "https"} if is_dev else {"https"}) or not parsed.netloc:
        raise ValueError(f"{field} must be a valid HTTPS URL.")
    return value


def validate_provider_settings(provider: Provider, values: dict, secret: str) -> dict:
    if provider == "resident_payments":
        provider_name = str(values.get("provider", "stripe")).strip().lower()
        publishable = str(values.get("publishable_key", "")).strip()
        if provider_name != "stripe":
            raise ValueError("resident_payments provider must be stripe.")
        if secret and not secret.startswith(("sk_test_", "sk_live_")):
            raise ValueError("Stripe secret API key must start with sk_test_ or sk_live_.")
        if not publishable.startswith(("pk_test_", "pk_live_")):
            raise ValueError("Stripe publishable key must start with pk_test_ or pk_live_.")
        if secret and (secret.startswith("sk_live_") != publishable.startswith("pk_live_")):
            raise ValueError("Stripe secret and publishable key modes must match.")
        return {
            "provider": provider_name,
            "publishable_key": publishable,
            "api_url": _https_url(
                str(values.get("api_url") or "https://api.stripe.com/v1/payment_intents"),
                "api_url",
            ),
        }
    if provider == "screening":
        provider_name = str(values.get("provider_name", "")).strip()
        if not provider_name:
            raise ValueError("screening provider_name is required.")
        attempts = int(values.get("poll_attempts", 5))
        interval = float(values.get("poll_interval_seconds", 2.0))
        if not 1 <= attempts <= 20 or not 0 <= interval <= 60:
            raise ValueError("Screening polling values are outside the allowed range.")
        return {
            "provider_name": provider_name,
            "api_url": _https_url(str(values.get("api_url", "")), "api_url"),
            "health_url": _https_url(
                str(values.get("health_url", "")), "health_url", allow_empty=True
            ),
            "poll_attempts": attempts,
            "poll_interval_seconds": interval,
        }
    environment = str(values.get("environment", "sandbox")).strip().lower()
    if environment not in PLAID_BASE_URLS:
        raise ValueError("Plaid environment must be sandbox, development, or production.")
    base_url = _https_url(
        str(values.get("api_base_url") or PLAID_BASE_URLS[environment]), "api_base_url"
    )
    if base_url != PLAID_BASE_URLS[environment]:
        raise ValueError("Plaid api_base_url must match the selected environment.")
    client_id = str(values.get("client_id", "")).strip()
    if not client_id:
        raise ValueError("Plaid client_id is required.")
    countries = tuple(
        dict.fromkeys(str(code).strip().upper() for code in values.get("country_codes", ["US"]) if str(code).strip())
    )
    if not countries or any(len(code) != 2 or not code.isalpha() for code in countries):
        raise ValueError("Plaid country_codes must contain two-letter country codes.")
    return {
        "client_id": client_id,
        "environment": environment,
        "api_base_url": base_url,
        "country_codes": list(countries),
        "redirect_uri": _https_url(
            str(values.get("redirect_uri", "")), "redirect_uri", allow_empty=True
        ),
        "webhook_url": _https_url(
            str(values.get("webhook_url", "")), "webhook_url", allow_empty=True
        ),
        "applicant_redirect_uri": _https_url(
            str(values.get("applicant_redirect_uri", "")),
            "applicant_redirect_uri",
            allow_empty=True,
        ),
        "applicant_verification_enabled": bool(values.get("applicant_verification_enabled", False)),
    }


def _from_row(provider: Provider, row: OrganizationIntegrationConfig) -> IntegrationSettings:
    data = row.settings_json or {}
    secret = decrypt_secret(row.secret_encrypted) if row.secret_encrypted else ""
    if provider == "resident_payments":
        return ResidentPaymentsSettings(
            provider=data.get("provider", "stripe"), secret_api_key=secret,
            publishable_key=data.get("publishable_key", ""), api_url=data.get("api_url", ""),
            is_enabled=row.is_enabled, source="tenant",
        )
    if provider == "screening":
        return ScreeningSettings(
            provider_name=data.get("provider_name", ""), api_key=secret,
            api_url=data.get("api_url", ""), health_url=data.get("health_url", ""),
            poll_attempts=int(data.get("poll_attempts", 5)),
            poll_interval_seconds=float(data.get("poll_interval_seconds", 2.0)),
            is_enabled=row.is_enabled, source="tenant",
        )
    return PlaidSettings(
        client_id=data.get("client_id", ""), secret=secret,
        environment=data.get("environment", "sandbox"), api_base_url=data.get("api_base_url", ""),
        country_codes=tuple(data.get("country_codes", ["US"])),
        redirect_uri=data.get("redirect_uri", ""), webhook_url=data.get("webhook_url", ""),
        applicant_verification_enabled=bool(data.get("applicant_verification_enabled", False)),
        applicant_redirect_uri=data.get("applicant_redirect_uri", ""),
        timeout_seconds=settings.PLAID_TIMEOUT_SECONDS,
        is_enabled=row.is_enabled, source="tenant",
    )


def legacy_settings(provider: Provider) -> IntegrationSettings:
    if provider == "resident_payments":
        configured = bool(settings.PAYMENTS_API_KEY and settings.PAYMENTS_PUBLISHABLE_KEY)
        return ResidentPaymentsSettings(
            provider=settings.PAYMENTS_PROVIDER or "stripe", secret_api_key=settings.PAYMENTS_API_KEY,
            publishable_key=settings.PAYMENTS_PUBLISHABLE_KEY,
            api_url=settings.PAYMENTS_API_URL or "https://api.stripe.com/v1/payment_intents",
            is_enabled=configured, source="legacy_env" if configured else "unconfigured",
        )
    if provider == "screening":
        configured = bool(settings.SCREENING_API_KEY and settings.SCREENING_API_URL)
        return ScreeningSettings(
            provider_name=settings.SCREENING_PROVIDER or "", api_key=settings.SCREENING_API_KEY,
            api_url=settings.SCREENING_API_URL, health_url=settings.SCREENING_HEALTH_URL,
            poll_attempts=settings.SCREENING_POLL_ATTEMPTS,
            poll_interval_seconds=settings.SCREENING_POLL_INTERVAL_SECONDS,
            is_enabled=configured, source="legacy_env" if configured else "unconfigured",
        )
    configured = bool(settings.PLAID_CLIENT_ID and settings.PLAID_SECRET)
    return PlaidSettings(
        client_id=settings.PLAID_CLIENT_ID, secret=settings.PLAID_SECRET,
        environment=settings.PLAID_ENV, api_base_url=settings.PLAID_API_BASE_URL,
        country_codes=tuple(c.strip().upper() for c in (settings.PLAID_COUNTRY_CODES or "US").split(",") if c.strip()),
        redirect_uri=settings.PLAID_REDIRECT_URI, webhook_url="", applicant_verification_enabled=False,
        applicant_redirect_uri="",
        timeout_seconds=settings.PLAID_TIMEOUT_SECONDS,
        is_enabled=configured, source="legacy_env" if configured else "unconfigured",
    )


async def get_config_row(
    db: AsyncSession, organization_id: uuid.UUID, provider: Provider
) -> OrganizationIntegrationConfig | None:
    return (
        await db.execute(
            select(OrganizationIntegrationConfig).where(
                OrganizationIntegrationConfig.organization_id == organization_id,
                OrganizationIntegrationConfig.provider == provider,
            )
        )
    ).scalar_one_or_none()


async def resolve(
    db: AsyncSession, organization_id: uuid.UUID, provider: Provider
) -> IntegrationSettings:
    row = await get_config_row(db, organization_id, provider)
    return _from_row(provider, row) if row else legacy_settings(provider)


def safe_config(provider: Provider, resolved: IntegrationSettings, row=None) -> dict:
    data = asdict(resolved)
    secret_name = {"resident_payments": "secret_api_key", "screening": "api_key", "plaid": "secret"}[provider]
    secret = str(data.pop(secret_name, ""))
    data["secret_hint"] = mask_secret(secret) if secret else None
    data["provider"] = provider
    data["last_verified_at"] = row.last_verified_at if row else None
    data["last_verify_ok"] = row.last_verify_ok if row else None
    data["last_verify_error"] = row.last_verify_error if row else None
    return data
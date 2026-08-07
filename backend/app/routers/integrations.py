"""Organization-admin integration readiness API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.user import User
from app.services import integration_readiness
from app.services import organization_integration_settings as org_settings
from app.models.organization_integration_config import OrganizationIntegrationConfig
from app.utils.crypto import encrypt_secret

router = APIRouter()
OrgAdmin = require_role("admin")


class IntegrationReadinessOut(BaseModel):
    provider: str
    scope: Literal["organization"]
    configured: bool
    verified: bool | None = None
    verification_supported: bool
    mode: Literal["sandbox", "live", "unknown"]
    missing_config: list[str] = Field(default_factory=list)
    last_verified_at: datetime | None = None
    last_error: str | None = None
    detail: str | None = None
    source: Literal["tenant", "legacy_env", "unconfigured"]


class IntegrationConfigInput(BaseModel):
    is_enabled: bool = True
    secret: str | None = None
    clear_secret: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)


class IntegrationConfigOut(BaseModel):
    provider: str
    source: Literal["tenant", "legacy_env", "unconfigured"]
    is_enabled: bool
    secret_hint: str | None = None
    last_verified_at: datetime | None = None
    last_verify_ok: bool | None = None
    last_verify_error: str | None = None
    model_config = {"extra": "allow"}


class VerificationOut(BaseModel):
    provider: str
    ok: bool
    verification_supported: bool
    error: str | None = None


def _org_id(user: User) -> uuid.UUID:
    if user.organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization required")
    return user.organization_id


@router.get("/readiness", response_model=list[IntegrationReadinessOut])
async def readiness(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(OrgAdmin)
):
    return await integration_readiness.get_readiness(db, _org_id(current_user))


def _provider(value: str) -> org_settings.Provider:
    if value not in org_settings.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unsupported integration provider")
    return value  # type: ignore[return-value]


@router.get("/config/{provider}", response_model=IntegrationConfigOut)
async def get_config(
    provider: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(OrgAdmin)
):
    provider_name = _provider(provider)
    organization_id = _org_id(current_user)
    row = await org_settings.get_config_row(db, organization_id, provider_name)
    resolved = await org_settings.resolve(db, organization_id, provider_name)
    return org_settings.safe_config(provider_name, resolved, row)


@router.put("/config/{provider}", response_model=IntegrationConfigOut)
async def put_config(
    provider: str, payload: IntegrationConfigInput,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(OrgAdmin),
):
    provider_name = _provider(provider)
    organization_id = _org_id(current_user)
    row = await org_settings.get_config_row(db, organization_id, provider_name)
    existing_secret = row.secret_encrypted if row else None
    secret = (payload.secret or "").strip()
    if not secret and existing_secret and not payload.clear_secret:
        from app.utils.crypto import decrypt_secret
        secret = decrypt_secret(existing_secret)
    if not secret and not payload.clear_secret:
        fallback = org_settings.legacy_settings(provider_name)
        secret = getattr(fallback, {"resident_payments": "secret_api_key", "screening": "api_key", "plaid": "secret"}[provider_name])
    if not secret and not payload.clear_secret:
        raise HTTPException(
            status_code=422,
            detail="A secret is required. Set clear_secret=true only to explicitly clear it.",
        )
    try:
        validated = org_settings.validate_provider_settings(provider_name, payload.settings, secret)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        row = OrganizationIntegrationConfig(organization_id=organization_id, provider=provider_name)
        db.add(row)
    row.settings_json = validated
    row.is_enabled = payload.is_enabled
    row.secret_encrypted = encrypt_secret(secret) if secret else None
    row.updated_by_id = current_user.id
    row.last_verified_at = None
    row.last_verify_ok = None
    row.last_verify_error = None
    await db.commit()
    await db.refresh(row)
    return org_settings.safe_config(provider_name, await org_settings.resolve(db, organization_id, provider_name), row)


@router.delete("/config/{provider}", status_code=204)
async def delete_config(
    provider: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(OrgAdmin)
):
    provider_name = _provider(provider)
    organization_id = _org_id(current_user)
    row = await org_settings.get_config_row(db, organization_id, provider_name)
    if row is None:
        row = OrganizationIntegrationConfig(
            organization_id=organization_id,
            provider=provider_name,
        )
        db.add(row)
    # Keep a disabled tenant override so legacy environment fallback cannot
    # silently reconnect an integration the organization explicitly removed.
    row.is_enabled = False
    row.secret_encrypted = None
    row.settings_json = {}
    row.last_verified_at = None
    row.last_verify_ok = None
    row.last_verify_error = None
    row.updated_by_id = current_user.id
    await db.commit()


@router.post("/{provider}/verify", response_model=VerificationOut)
async def verify(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(OrgAdmin),
):
    organization_id = _org_id(current_user)
    if provider == "resident_payments":
        result = await integration_readiness.verify_resident_payments(
            await org_settings.resolve(db, organization_id, "resident_payments")
        )
    elif provider == "screening":
        result = await integration_readiness.verify_screening(
            await org_settings.resolve(db, organization_id, "screening")
        )
    elif provider == "plaid":
        result = await integration_readiness.verify_plaid(
            await org_settings.resolve(db, organization_id, "plaid")
        )
    if provider == "sso":
        return await integration_readiness.verify_sso(db, organization_id)
    if provider not in org_settings.PROVIDERS:
        return VerificationOut(provider=provider, ok=False, verification_supported=False,
                               error="This provider requires its connection flow.")
    row = await org_settings.get_config_row(db, organization_id, _provider(provider))
    if row:
        row.last_verified_at = datetime.now(timezone.utc)
        row.last_verify_ok = result["ok"]
        row.last_verify_error = result["error"]
        await db.commit()
    return result
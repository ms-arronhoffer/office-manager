"""Organization-admin integration readiness API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.user import User
from app.services import integration_readiness

router = APIRouter()
OrgAdmin = require_role("admin")


class IntegrationReadinessOut(BaseModel):
    provider: str
    scope: Literal["organization", "platform"]
    configured: bool
    verified: bool | None = None
    verification_supported: bool
    mode: Literal["sandbox", "live", "unknown"]
    missing_config: list[str] = Field(default_factory=list)
    last_verified_at: datetime | None = None
    last_error: str | None = None
    detail: str | None = None


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


@router.post("/{provider}/verify", response_model=VerificationOut)
async def verify(
    provider: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(OrgAdmin),
):
    organization_id = _org_id(current_user)
    if provider == "resident_payments":
        return await integration_readiness.verify_resident_payments()
    if provider == "screening":
        return await integration_readiness.verify_screening()
    if provider == "sso":
        return await integration_readiness.verify_sso(db, organization_id)
    return VerificationOut(
        provider=provider,
        ok=False,
        verification_supported=False,
        error="This provider requires its sandbox connection flow or platform-admin verification.",
    )
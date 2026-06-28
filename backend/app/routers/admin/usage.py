"""Super-admin: feature-adoption analytics and AI token monitoring.

Powers the management console's "Usage & Adoption" view (which features are
used / unused, so high-value features can be identified and unused ones
removed) and per-org / platform-wide token monitoring for cost control and
tier-limit enforcement.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services import entitlements as ent
from app.services import usage_service

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class FeatureAdoptionRow(BaseModel):
    feature: str
    label: str
    events: int
    org_count: int
    input_tokens: int
    output_tokens: int
    value_signal: int
    removal_candidate: bool


class FeatureAdoptionResponse(BaseModel):
    months: int
    periods: list[str]
    features: list[FeatureAdoptionRow]


class TopTokenOrg(BaseModel):
    organization_id: uuid.UUID
    organization_name: str | None
    plan: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int


class PlatformTokensResponse(BaseModel):
    period: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    top_orgs: list[TopTokenOrg]


class TokenWindow(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class OrgFeatureRow(BaseModel):
    feature: str
    label: str
    events: int
    input_tokens: int
    output_tokens: int


class OrgUsageResponse(BaseModel):
    organization_id: uuid.UUID
    period: str
    previous_period: str
    current: TokenWindow
    previous: TokenWindow
    input_token_limit: int | None
    output_token_limit: int | None
    by_feature: list[OrgFeatureRow]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/features", response_model=FeatureAdoptionResponse)
async def feature_adoption(
    months: int = Query(default=6, ge=1, le=24),
    org_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    """Feature usage broken down by feature over the last ``months`` periods."""
    rows = await usage_service.feature_adoption(db, months=months, org_id=org_id)
    return FeatureAdoptionResponse(
        months=months,
        periods=usage_service.recent_periods(months),
        features=[FeatureAdoptionRow(**r) for r in rows],
    )


@router.get("/tokens", response_model=PlatformTokensResponse)
async def platform_tokens(
    period: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    """Platform-wide token totals plus the top token-consuming orgs."""
    period = period or usage_service.current_period()
    totals = await usage_service.platform_token_totals(db, period)
    top = await usage_service.top_token_orgs(db, period=period, limit=limit)

    org_ids = [t["organization_id"] for t in top]
    orgs: dict[uuid.UUID, Organization] = {}
    if org_ids:
        rows = await db.execute(
            select(Organization).where(Organization.id.in_(org_ids))
        )
        orgs = {o.id: o for o in rows.scalars().all()}

    top_orgs = [
        TopTokenOrg(
            organization_id=t["organization_id"],
            organization_name=getattr(orgs.get(t["organization_id"]), "name", None),
            plan=getattr(orgs.get(t["organization_id"]), "plan", None),
            input_tokens=t["input_tokens"],
            output_tokens=t["output_tokens"],
            total_tokens=t["total_tokens"],
        )
        for t in top
    ]
    return PlatformTokensResponse(
        period=period,
        input_tokens=totals["input_tokens"],
        output_tokens=totals["output_tokens"],
        total_tokens=totals["input_tokens"] + totals["output_tokens"],
        top_orgs=top_orgs,
    )


@router.get("/orgs/{org_id}", response_model=OrgUsageResponse)
async def org_usage(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    """Per-org token usage (current + prior period) and feature breakdown."""
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )

    summary = await usage_service.org_token_summary(db, org_id)
    return OrgUsageResponse(
        organization_id=org_id,
        period=summary["period"],
        previous_period=summary["previous_period"],
        current=TokenWindow(**summary["current"]),
        previous=TokenWindow(**summary["previous"]),
        input_token_limit=ent.get_limit(org, "monthly_ai_input_tokens"),
        output_token_limit=ent.get_limit(org, "monthly_ai_output_tokens"),
        by_feature=[OrgFeatureRow(**r) for r in summary["by_feature"]],
    )

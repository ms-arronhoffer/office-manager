import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role, require_super_admin
from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.config import settings
from app.services.stripe_settings import resolve_stripe_secret_key
from app.database import get_db
from app.main import limiter
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.office import Office
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import (
    OrganizationCreate, OrganizationResponse, OrganizationUpdate,
    SignupRequest, SignupResponse,
)
from app.services import entitlements as ent
from app.services import categories as cat
from app.services.email_verification_service import issue_verification_token, send_verification_email

router = APIRouter()

logger = logging.getLogger(__name__)


class CategoriesUpdate(BaseModel):
    """Org-admin request to replace the org's enabled primary categories."""

    enabled_categories: list[str]


def _slug_from_name(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:100]


# ─── Public: Self-service signup ───────────────────────────────────────────────

@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def signup(
    request: Request,
    payload: SignupRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new organization and admin user. No authentication required."""
    # Check for duplicate email
    existing_user = await db.execute(select(User).where(User.email == payload.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Generate a unique slug
    base_slug = _slug_from_name(payload.org_name) or "org"
    slug = base_slug
    suffix = 1
    while True:
        existing_slug = await db.execute(select(Organization).where(Organization.slug == slug))
        if not existing_slug.scalar_one_or_none():
            break
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    # Create organization
    org = Organization(
        name=payload.org_name,
        slug=slug,
        plan="starter",
        is_active=True,
        onboarding_complete=False,
        # New self-service orgs start on a free trial with no paid subscription.
        # Model this explicitly as ``payment_status="trial"`` (rather than the
        # "active" default, which reads as a paying customer) so the admin
        # console, metrics, and billing-hygiene treat them as trials.
        payment_status="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=settings.TRIAL_DAYS),
    )
    db.add(org)
    await db.flush()  # get org.id before creating user

    # Create admin user
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(org)
    await db.refresh(user)
    verification_token = await issue_verification_token(user, db)
    send_verification_email(user, verification_token, background_tasks)

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": str(org.id),
        "is_super_admin": False,
    })
    return SignupResponse(access_token=token, organization=OrganizationResponse.model_validate(org))

@router.get("/", response_model=list[OrganizationResponse], dependencies=[Depends(require_super_admin())])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organization).order_by(Organization.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_super_admin())])
async def create_organization(payload: OrganizationCreate, db: AsyncSession = Depends(get_db)):
    slug = payload.slug or _slug_from_name(payload.name)
    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")
    org = Organization(
        name=payload.name,
        slug=slug,
        plan=payload.plan,
        max_seats=payload.max_seats,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/me", response_model=OrganizationResponse)
async def get_my_organization(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's organization. All authenticated users can call this."""
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organization assigned")
    result = await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.get("/me/entitlements")
async def get_my_entitlements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Effective entitlements, billing access state, and usage for the current org.

    Powers the primary app's plan-aware UI (gated nav, usage-vs-limit displays,
    upgrade prompts) so it no longer needs to hard-code plan feature lists.
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organization assigned")
    org = (
        await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    ).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    office_count = (
        await db.execute(
            select(func.count(Office.id)).where(
                Office.organization_id == org.id, Office.is_deleted.is_(False)
            )
        )
    ).scalar_one()
    seat_count = (
        await db.execute(
            select(func.count(User.id)).where(
                User.organization_id == org.id, User.is_active.is_(True)
            )
        )
    ).scalar_one()

    state = ent.org_access_state(org)
    return {
        "plan": org.plan,
        "effective_entitlements": ent.effective_entitlements(org),
        "plan_defaults": ent.plan_entitlements(org.plan),
        "overrides": ent.normalize_overrides(org.entitlement_overrides),
        "features": {k: ent.has_feature(org, k) for k in ent.FEATURE_KEYS},
        "limits": {k: ent.get_limit(org, k) for k in ent.LIMIT_KEYS},
        "categories": cat.categories_state(org),
        "usage": {"offices": office_count, "seats": seat_count},
        "access": {
            "state": state,
            "blocked": ent.is_access_blocked(state),
            "payment_status": org.payment_status,
            "is_active": org.is_active,
            "past_due_since": org.past_due_since.isoformat() if org.past_due_since else None,
            "grace_days": ent.PAST_DUE_GRACE_DAYS,
        },
    }


@router.get("/me/categories")
async def get_my_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current org's primary-category configuration.

    Powers the primary app's category-aware nav and route guards.
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organization assigned")
    org = (
        await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    ).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return cat.categories_state(org)


@router.put("/me/categories")
async def update_my_categories(
    payload: CategoriesUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Set the org-managed enabled primary categories (org-admin self-serve).

    Platform (super-admin) overrides always win over this org-managed list, so
    the returned ``effective`` set may differ from the requested list. Enforces
    that at least one category remains effectively enabled.
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organization assigned")
    org = (
        await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    ).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    try:
        cat.set_enabled_categories(org, payload.enabled_categories)
    except cat.CategoryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    await db.refresh(org)
    return cat.categories_state(org)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Super-admins can fetch any org; regular users can only fetch their own."""
    if not current_user.is_super_admin and current_user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: uuid.UUID,
    payload: OrganizationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Super-admins can update any org; org-admins can update their own (limited fields)."""
    if not current_user.is_super_admin and current_user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if not current_user.is_super_admin and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    update_data = payload.model_dump(exclude_unset=True)
    # Non-super-admins cannot change plan, is_active, or billing fields
    if not current_user.is_super_admin:
        for restricted in ("plan", "is_active", "stripe_customer_id", "stripe_subscription_id"):
            update_data.pop(restricted, None)

    for field, value in update_data.items():
        setattr(org, field, value)

    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_organization(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete the current organization. Cancels Stripe subscription if present.

    This is irreversible from the tenant's perspective. Data is preserved for
    compliance; a super-admin hard-delete can be performed separately.
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organization assigned")

    result = await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Cancel Stripe subscription best-effort
    stripe_key = await resolve_stripe_secret_key(db)
    if org.stripe_subscription_id and stripe_key:
        try:
            import stripe
            stripe.api_key = stripe_key
            stripe.Subscription.delete(org.stripe_subscription_id)
        except Exception as e:
            logger.warning("Failed to cancel Stripe subscription on org self-delete: %s", e)

    org.is_active = False
    org.payment_status = "canceled"
    await db.commit()

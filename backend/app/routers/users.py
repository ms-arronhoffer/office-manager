import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.auth.password import hash_password
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.user import RegisterRequest, UserResponse, UserUpdateRequest
from app.services import entitlements as ent

router = APIRouter()


async def _sync_stripe_seats(org: Organization, db: AsyncSession) -> None:
    """Best-effort: update the Stripe subscription quantity to match active seat count."""
    if not org or not org.stripe_subscription_id or not settings.STRIPE_SECRET_KEY:
        return
    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        seat_count = (
            await db.execute(
                select(func.count()).select_from(User).where(
                    User.organization_id == org.id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one()
        sub = stripe.Subscription.retrieve(org.stripe_subscription_id)
        item_id = sub["items"]["data"][0]["id"]
        stripe.SubscriptionItem.modify(item_id, quantity=max(1, seat_count))
    except Exception as e:
        print(f"[STRIPE] Failed to sync seat quantity: {e}")


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    org_id = current_user.organization_id
    total = (
        await db.execute(
            select(func.count(User.id)).where(User.organization_id == org_id)
        )
    ).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User)
        .where(User.organization_id == org_id)
        .order_by(User.display_name)
        .offset(offset)
        .limit(page_size)
    )
    users = result.scalars().all()
    return PaginatedResponse(
        items=users,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    org_id = current_user.organization_id

    # Enforce seat limit if the org has one configured (effective = override → legacy → plan)
    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = org_result.scalar_one_or_none()
    seat_limit = ent.get_limit(org, "max_seats") if org else None
    if seat_limit is not None:
        seat_count = (
            await db.execute(
                select(func.count()).select_from(User).where(
                    User.organization_id == org_id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one()
        if seat_count >= seat_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Seat limit reached ({seat_limit} seats on {org.plan} plan). "
                       "Upgrade your plan to add more users.",
            )

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    new_user = User(
        email=data.email,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        auth_provider="internal",
        role=data.role,
        is_active=True,
        organization_id=org_id,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    # Update Stripe subscription quantity (best-effort)
    await _sync_stripe_seats(org, db)
    return new_user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.organization_id == current_user.organization_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(target, field, value)

    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.organization_id == current_user.organization_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    target.is_active = False
    await db.commit()
    # Update Stripe subscription quantity (best-effort)
    org_result = await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    org = org_result.scalar_one_or_none()
    await _sync_stripe_seats(org, db)

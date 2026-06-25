"""Super-admin: billing oversight + Stripe cancel/restore."""
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services.activity_service import log_activity

router = APIRouter()


class BillingRow(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    payment_status: str
    is_active: bool
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    max_seats: int | None
    seat_count: int
    trial_ends_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedBilling(BaseModel):
    items: list[BillingRow]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("", response_model=PaginatedBilling)
async def list_billing(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    payment_status: str | None = Query(default=None),
    plan: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    stmt = select(Organization)
    if payment_status:
        stmt = stmt.where(Organization.payment_status == payment_status)
    if plan:
        stmt = stmt.where(Organization.plan == plan)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(Organization.created_at.desc()).offset(offset).limit(page_size))
    orgs = result.scalars().all()

    # Seat counts
    org_ids = [o.id for o in orgs]
    seat_counts: dict[uuid.UUID, int] = {}
    if org_ids:
        seat_rows = await db.execute(
            select(User.organization_id, func.count(User.id))
            .where(User.organization_id.in_(org_ids), User.is_active.is_(True))
            .group_by(User.organization_id)
        )
        seat_counts = {r[0]: r[1] for r in seat_rows.all()}

    items = [
        BillingRow(
            id=o.id,
            name=o.name,
            plan=o.plan,
            payment_status=o.payment_status,
            is_active=o.is_active,
            stripe_customer_id=o.stripe_customer_id,
            stripe_subscription_id=o.stripe_subscription_id,
            max_seats=o.max_seats,
            seat_count=seat_counts.get(o.id, 0),
            trial_ends_at=o.trial_ends_at,
            created_at=o.created_at,
        )
        for o in orgs
    ]
    return PaginatedBilling(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("/{org_id}/cancel", response_model=BillingRow)
async def cancel_subscription(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Cancel Stripe subscription if configured
    if org.stripe_subscription_id and settings.STRIPE_SECRET_KEY:
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            stripe.Subscription.cancel(org.stripe_subscription_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe cancellation failed: {exc}",
            ) from exc

    org.is_active = False
    org.payment_status = "canceled"
    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes={"action": "subscription_canceled"},
    )

    seat_rows = await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id, User.is_active.is_(True))
    )
    seat_count = seat_rows.scalar_one()

    return BillingRow(
        id=org.id,
        name=org.name,
        plan=org.plan,
        payment_status=org.payment_status,
        is_active=org.is_active,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        max_seats=org.max_seats,
        seat_count=seat_count,
        trial_ends_at=org.trial_ends_at,
        created_at=org.created_at,
    )


@router.post("/{org_id}/restore", response_model=BillingRow)
async def restore_subscription(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org.is_active = True
    org.payment_status = "active"
    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes={"action": "subscription_restored"},
    )

    seat_rows = await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id, User.is_active.is_(True))
    )
    seat_count = seat_rows.scalar_one()

    return BillingRow(
        id=org.id,
        name=org.name,
        plan=org.plan,
        payment_status=org.payment_status,
        is_active=org.is_active,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        max_seats=org.max_seats,
        seat_count=seat_count,
        trial_ends_at=org.trial_ends_at,
        created_at=org.created_at,
    )

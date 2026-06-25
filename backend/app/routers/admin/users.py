"""Super-admin: cross-org user management."""
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.services.activity_service import log_activity

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class AdminUserItem(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    is_super_admin: bool
    organization_id: uuid.UUID | None
    organization_name: str | None
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserPatch(BaseModel):
    is_active: bool | None = None
    role: str | None = None
    is_super_admin: bool | None = None
    organization_id: uuid.UUID | None = None


class PaginatedUsers(BaseModel):
    items: list[AdminUserItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_org_names(
    db: AsyncSession, org_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not org_ids:
        return {}
    rows = await db.execute(
        select(Organization.id, Organization.name).where(Organization.id.in_(org_ids))
    )
    return {r[0]: r[1] for r in rows.all()}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedUsers)
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, description="Filter by email or display_name"),
    org_id: uuid.UUID | None = Query(default=None),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    is_super_admin: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    stmt = select(User)
    if search:
        stmt = stmt.where(
            (User.email.ilike(f"%{search}%")) | (User.display_name.ilike(f"%{search}%"))
        )
    if org_id:
        stmt = stmt.where(User.organization_id == org_id)
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if is_super_admin is not None:
        stmt = stmt.where(User.is_super_admin == is_super_admin)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(User.created_at.desc()).offset(offset).limit(page_size))
    users = result.scalars().all()

    org_ids = {u.organization_id for u in users if u.organization_id}
    org_names = await _resolve_org_names(db, org_ids)

    items = [
        AdminUserItem(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
            is_active=u.is_active,
            is_super_admin=u.is_super_admin,
            organization_id=u.organization_id,
            organization_name=org_names.get(u.organization_id) if u.organization_id else None,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        )
        for u in users
    ]
    return PaginatedUsers(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.patch("/{user_id}", response_model=AdminUserItem)
async def patch_user(
    user_id: uuid.UUID,
    payload: AdminUserPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Validate org_id if being reassigned
    update_data = payload.model_dump(exclude_unset=True)
    if "organization_id" in update_data and update_data["organization_id"] is not None:
        org = (
            await db.execute(
                select(Organization).where(Organization.id == update_data["organization_id"])
            )
        ).scalar_one_or_none()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target organization not found",
            )

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="user",
        entity_id=user_id,
        entity_label=user.display_name,
        changes=update_data,
    )

    org_name: str | None = None
    if user.organization_id:
        org = (
            await db.execute(select(Organization).where(Organization.id == user.organization_id))
        ).scalar_one_or_none()
        org_name = org.name if org else None

    return AdminUserItem(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        is_super_admin=user.is_super_admin,
        organization_id=user.organization_id,
        organization_name=org_name,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )

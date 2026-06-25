import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.management_company import ManagementCompany
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.management_company import (
    ManagementCompanyCreate,
    ManagementCompanyResponse,
    ManagementCompanyUpdate,
)
from app.services.activity_service import log_activity, compute_changes
from app.utils.sorting import apply_sorting

router = APIRouter()


async def _load(db: AsyncSession, company_id: uuid.UUID, org_id: uuid.UUID) -> ManagementCompany:
    result = await db.execute(
        select(ManagementCompany).where(
            ManagementCompany.id == company_id,
            ManagementCompany.is_deleted.is_(False),
            ManagementCompany.organization_id == org_id,
        )
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Management company not found")
    return company


@router.get("", response_model=PaginatedResponse[ManagementCompanyResponse])
async def list_management_companies(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    search: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = (
        select(ManagementCompany)
        .where(ManagementCompany.is_deleted.is_(False))
        .where(ManagementCompany.organization_id == current_user.organization_id)
    )

    if search:
        term = f"%{search}%"
        base = base.where(
            or_(
                ManagementCompany.name.ilike(term),
                ManagementCompany.contact_name.ilike(term),
                ManagementCompany.contact_email.ilike(term),
            )
        )

    count_stmt = select(func.count()).select_from(base.with_only_columns(ManagementCompany.id).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _SORT_COLS = {
        "name": ManagementCompany.name,
        "contact_name": ManagementCompany.contact_name,
        "created_at": ManagementCompany.created_at,
    }
    stmt = apply_sorting(base, sort_by, sort_order, _SORT_COLS, [ManagementCompany.name])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    companies = result.scalars().all()

    return PaginatedResponse(
        items=[ManagementCompanyResponse.model_validate(c, from_attributes=True) for c in companies],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{company_id}", response_model=ManagementCompanyResponse)
async def get_management_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = await _load(db, company_id, current_user.organization_id)
    return ManagementCompanyResponse.model_validate(company, from_attributes=True)


@router.post("", response_model=ManagementCompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_management_company(
    payload: ManagementCompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    company = ManagementCompany(**payload.model_dump(), organization_id=current_user.organization_id)
    db.add(company)
    await db.commit()
    await db.refresh(company)
    await log_activity(
        db, user=current_user, action="created", entity_type="management_company",
        entity_id=company.id, entity_label=company.name,
    )
    return ManagementCompanyResponse.model_validate(company, from_attributes=True)


@router.put("/{company_id}", response_model=ManagementCompanyResponse)
async def update_management_company(
    company_id: uuid.UUID,
    payload: ManagementCompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    company = await _load(db, company_id, current_user.organization_id)
    update_data = payload.model_dump(exclude_unset=True)
    old_values = {k: getattr(company, k, None) for k in update_data}
    for field, value in update_data.items():
        setattr(company, field, value)
    await db.commit()
    await db.refresh(company)
    changes = compute_changes(old_values, update_data)
    await log_activity(
        db, user=current_user, action="updated", entity_type="management_company",
        entity_id=company.id, entity_label=company.name, changes=changes,
    )
    return ManagementCompanyResponse.model_validate(company, from_attributes=True)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_management_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    company = await _load(db, company_id, current_user.organization_id)
    label = company.name
    company.is_deleted = True
    company.deleted_at = _utcnow()
    await db.commit()
    await log_activity(
        db, user=current_user, action="deleted", entity_type="management_company",
        entity_id=company_id, entity_label=label,
    )


@router.patch("/{company_id}/restore", response_model=ManagementCompanyResponse)
async def restore_management_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(ManagementCompany).where(
            ManagementCompany.id == company_id,
            ManagementCompany.is_deleted.is_(True),
            ManagementCompany.organization_id == current_user.organization_id,
        )
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Management company not found or not deleted")
    company.is_deleted = False
    company.deleted_at = None
    await db.commit()
    await db.refresh(company)
    await log_activity(
        db, user=current_user, action="updated", entity_type="management_company",
        entity_id=company_id, entity_label=company.name,
    )
    return ManagementCompanyResponse.model_validate(company, from_attributes=True)

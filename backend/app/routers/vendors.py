import math
import uuid
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.vendor import Vendor, vendor_offices
from app.models.office import Office
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.vendor import VendorCreate, VendorResponse, VendorUpdate
from app.services.activity_service import log_activity, compute_changes
from app.utils.sorting import apply_sorting
from app.utils.tenant_scope import load_or_404

router = APIRouter()


async def _sync_offices(db: AsyncSession, vendor_id: uuid.UUID, office_ids: list[uuid.UUID]) -> None:
    """Replace all office assignments for a vendor."""
    await db.execute(delete(vendor_offices).where(vendor_offices.c.vendor_id == vendor_id))
    for oid in office_ids:
        await db.execute(vendor_offices.insert().values(vendor_id=vendor_id, office_id=oid))


async def _load_vendor(db: AsyncSession, vendor_id: uuid.UUID, org_id: uuid.UUID) -> Vendor:
    vendor = await load_or_404(
        db,
        Vendor,
        vendor_id,
        org_id,
        extra_filters=[Vendor.is_deleted.is_(False)],
        detail="Vendor not found",
    )
    await db.refresh(vendor, attribute_names=["offices"])
    return vendor


@router.get("/export")
async def export_vendors(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Vendor)
        .options(joinedload(Vendor.offices))
        .where(Vendor.is_deleted.is_(False))
        .where(Vendor.organization_id == current_user.organization_id)
        .order_by(Vendor.company_name)
    )
    vendors = result.scalars().unique().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Company", "Services", "Contact", "Email", "Phone", "Address", "Preferred", "Offices"])
    for v in vendors:
        offices_str = "; ".join(o.location_name for o in v.offices)
        writer.writerow([
            v.company_name, v.services, v.contact_name,
            v.contact_email, v.contact_phone, v.address,
            v.is_preferred, offices_str,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vendors.csv"},
    )


@router.get("", response_model=PaginatedResponse[VendorResponse])
async def list_vendors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    search: str | None = Query(default=None),
    office_id: uuid.UUID | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = (
        select(Vendor)
        .options(joinedload(Vendor.offices))
        .where(Vendor.is_deleted.is_(False))
        .where(Vendor.organization_id == current_user.organization_id)
    )

    if search:
        term = f"%{search}%"
        base = base.where(
            or_(
                Vendor.company_name.ilike(term),
                Vendor.contact_name.ilike(term),
                Vendor.services.ilike(term),
            )
        )

    if office_id is not None:
        base = base.join(vendor_offices).where(vendor_offices.c.office_id == office_id)

    count_stmt = select(func.count()).select_from(
        base.with_only_columns(Vendor.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _VENDOR_SORT_COLS = {
        "company_name": Vendor.company_name,
        "contact_name": Vendor.contact_name,
        "is_preferred": Vendor.is_preferred,
        "created_at": Vendor.created_at,
    }
    stmt = apply_sorting(base, sort_by, sort_order, _VENDOR_SORT_COLS, [Vendor.company_name])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    vendors = result.scalars().unique().all()

    return PaginatedResponse(
        items=[VendorResponse.model_validate(v, from_attributes=True) for v in vendors],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vendor = await _load_vendor(db, vendor_id, current_user.organization_id)
    return VendorResponse.model_validate(vendor, from_attributes=True)


@router.post("", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: VendorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    data = payload.model_dump(exclude={"office_ids"})
    vendor = Vendor(**data, organization_id=current_user.organization_id)
    db.add(vendor)
    await db.flush()

    if payload.office_ids:
        await _sync_offices(db, vendor.id, payload.office_ids)

    await db.commit()
    await log_activity(
        db, user=current_user, action="created", entity_type="vendor",
        entity_id=vendor.id, entity_label=vendor.company_name,
    )

    vendor = await _load_vendor(db, vendor.id, current_user.organization_id)
    return VendorResponse.model_validate(vendor, from_attributes=True)


@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: uuid.UUID,
    payload: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    vendor = await _load_vendor(db, vendor_id, current_user.organization_id)

    try:
        update_data = payload.model_dump(exclude_unset=True, exclude={"office_ids"})
        old_values = {k: getattr(vendor, k, None) for k in update_data}
        for field, value in update_data.items():
            if hasattr(vendor, field):
                setattr(vendor, field, value)

        if payload.office_ids is not None:
            await _sync_offices(db, vendor_id, payload.office_ids)

        await db.commit()
        changes = compute_changes(old_values, update_data)
        try:
            await log_activity(
                db, user=current_user, action="updated", entity_type="vendor",
                entity_id=vendor.id, entity_label=vendor.company_name, changes=changes,
            )
        except Exception:
            pass
    except Exception:
        pass

    try:
        vendor = await _load_vendor(db, vendor_id, current_user.organization_id)
        return VendorResponse.model_validate(vendor, from_attributes=True)
    except Exception:
        return VendorResponse.model_validate(vendor, from_attributes=True)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vendor(
    vendor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    vendor = await _load_vendor(db, vendor_id, current_user.organization_id)
    label = vendor.company_name
    vendor.is_deleted = True
    vendor.deleted_at = _utcnow()
    await db.commit()
    await log_activity(
        db, user=current_user, action="deleted", entity_type="vendor",
        entity_id=vendor_id, entity_label=label,
    )


@router.patch("/{vendor_id}/restore", response_model=VendorResponse)
async def restore_vendor(
    vendor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.is_deleted.is_(True), Vendor.organization_id == current_user.organization_id)
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found or not deleted")
    vendor.is_deleted = False
    vendor.deleted_at = None
    await db.commit()
    await log_activity(
        db, user=current_user, action="updated", entity_type="vendor",
        entity_id=vendor_id, entity_label=vendor.company_name,
    )
    vendor = await _load_vendor(db, vendor_id, current_user.organization_id)
    return VendorResponse.model_validate(vendor, from_attributes=True)

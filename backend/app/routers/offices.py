import csv
import io
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.services import entitlements as ent
from app.models.base import _utcnow
from app.models.hvac_contract import HvacContract
from app.models.landlord import Landlord, LandlordAdditionalName, LandlordContact
from app.models.office import Manager, Office
from app.models.organization import Organization
from app.models.vendor import Vendor, vendor_offices
from app.utils.sorting import apply_sorting
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.hvac_contract import HvacContractResponse
from app.schemas.landlord import LandlordResponse
from app.schemas.office import OfficeCreate, OfficeResponse, OfficeUpdate
from app.schemas.vendor import VendorResponse
from app.services.activity_service import log_activity, compute_changes
from app.utils.search_vectors import update_search_vector

router = APIRouter()


@router.get("/export")
async def export_offices(
    region_number: int | None = Query(default=None),
    manager_id: uuid.UUID | None = Query(default=None),
    location_type: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    state: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Office).options(joinedload(Office.manager)).where(
        Office.is_deleted.is_(False),
        Office.organization_id == current_user.organization_id,
    )

    if region_number is not None:
        stmt = stmt.where(Office.region_number == region_number)
    if manager_id is not None:
        stmt = stmt.where(Office.manager_id == manager_id)
    if location_type is not None:
        stmt = stmt.where(Office.location_type == location_type)
    if sector is not None:
        stmt = stmt.where(Office.sector == sector)
    if state is not None:
        stmt = stmt.where(Office.state == state)
    if is_active is not None:
        stmt = stmt.where(Office.is_active == is_active)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Office.location_name.ilike(term),
                Office.city.ilike(term),
                Office.state.ilike(term),
                Office.other_names.ilike(term),
            )
        )

    stmt = stmt.order_by(Office.office_number)
    result = await db.execute(stmt)
    offices = result.scalars().unique().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Office Number", "Region", "Location Name", "Location Type", "Manager",
        "Active", "Address", "City", "State", "Zip", "Phone", "Fax", "Email",
        "Sector", "Mail/Shipping", "Notes",
    ])
    for o in offices:
        writer.writerow([
            o.office_number, o.region_number, o.location_name, o.location_type,
            o.manager.name if o.manager else "",
            "Yes" if o.is_active else "No",
            o.address_line_1, o.city, o.state, o.zip_code,
            o.phone_number, o.fax, o.email,
            o.sector, o.mail_shipping, o.notes,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=offices.csv"},
    )


@router.get("", response_model=PaginatedResponse[OfficeResponse])
async def list_offices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    region_number: int | None = Query(default=None),
    manager_id: uuid.UUID | None = Query(default=None),
    location_type: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    state: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Office).options(joinedload(Office.manager)).where(
        Office.is_deleted.is_(False),
        Office.organization_id == current_user.organization_id,
    )

    if region_number is not None:
        stmt = stmt.where(Office.region_number == region_number)
    if manager_id is not None:
        stmt = stmt.where(Office.manager_id == manager_id)
    if location_type is not None:
        stmt = stmt.where(Office.location_type == location_type)
    if sector is not None:
        stmt = stmt.where(Office.sector == sector)
    if state is not None:
        stmt = stmt.where(Office.state == state)
    if is_active is not None:
        stmt = stmt.where(Office.is_active == is_active)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Office.location_name.ilike(term),
                Office.city.ilike(term),
                Office.state.ilike(term),
                Office.other_names.ilike(term),
            )
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Sort + paginate
    _OFFICE_SORT_COLS = {
        "office_number": Office.office_number,
        "location_name": Office.location_name,
        "region_number": Office.region_number,
        "city": Office.city,
        "state": Office.state,
        "location_type": Office.location_type,
    }
    offset = (page - 1) * page_size
    stmt = apply_sorting(stmt, sort_by, sort_order, _OFFICE_SORT_COLS, [Office.office_number])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    offices = result.scalars().unique().all()

    return PaginatedResponse(
        items=[OfficeResponse.model_validate(o, from_attributes=True) for o in offices],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{office_id}", response_model=OfficeResponse)
async def get_office(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Office).options(joinedload(Office.manager)).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id)
    )
    office = result.scalar_one_or_none()
    if not office:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")
    return OfficeResponse.model_validate(office, from_attributes=True)


@router.post("", response_model=OfficeResponse, status_code=status.HTTP_201_CREATED)
async def create_office(
    payload: OfficeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    # Get organization and check office limit (via the central entitlements catalog)
    org_result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = org_result.scalar_one_or_none()
    limit = ent.get_limit(org, "max_offices") if org else None
    if limit is not None:
        office_count_result = await db.execute(
            select(func.count(Office.id)).where(
                Office.organization_id == current_user.organization_id,
                Office.is_deleted.is_(False)
            )
        )
        current_count = office_count_result.scalar_one()
        if current_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Office limit reached for the {org.plan} plan (max {limit}). "
                       "Please upgrade your plan to add more offices."
            )

    office = Office(**payload.model_dump(), organization_id=current_user.organization_id)
    db.add(office)
    await db.commit()
    await db.refresh(office)
    try:
        await log_activity(db, user=current_user, action="created", entity_type="office", entity_id=office.id, entity_label=office.location_name)
    except Exception:
        pass
    try:
        await update_search_vector(db, "offices", office.id)
    except Exception:
        pass

    # Reload with manager relationship
    try:
        result = await db.execute(
            select(Office).options(joinedload(Office.manager)).where(Office.id == office.id)
        )
        return OfficeResponse.model_validate(result.scalar_one(), from_attributes=True)
    except Exception:
        # If reload fails, return the office we already have
        return OfficeResponse.model_validate(office, from_attributes=True)


@router.put("/{office_id}", response_model=OfficeResponse)
async def update_office(
    office_id: uuid.UUID,
    payload: OfficeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(Office).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id))
    office = result.scalar_one_or_none()
    if not office:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")

    try:
        update_data = payload.model_dump(exclude_unset=True)
        old_values = {k: getattr(office, k, None) for k in update_data}
        for field, value in update_data.items():
            if hasattr(office, field):
                setattr(office, field, value)

        await db.commit()
        changes = compute_changes(old_values, update_data)
        try:
            await log_activity(db, user=current_user, action="updated", entity_type="office", entity_id=office.id, entity_label=office.location_name, changes=changes)
        except Exception:
            pass
        try:
            await update_search_vector(db, "offices", office.id)
        except Exception:
            pass
    except Exception:
        pass

    try:
        result = await db.execute(
            select(Office).options(joinedload(Office.manager)).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id)
        )
        return OfficeResponse.model_validate(result.scalar_one(), from_attributes=True)
    except Exception:
        return OfficeResponse.model_validate(office, from_attributes=True)


@router.delete("/{office_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_office(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Office).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id))
    office = result.scalar_one_or_none()
    if not office:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")
    label = office.location_name
    office.is_deleted = True
    office.deleted_at = _utcnow()
    await db.commit()
    try:
        await log_activity(db, user=current_user, action="deleted", entity_type="office", entity_id=office_id, entity_label=label)
    except Exception:
        pass


@router.patch("/{office_id}/restore", response_model=OfficeResponse)
async def restore_office(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Office).where(Office.id == office_id, Office.is_deleted.is_(True), Office.organization_id == current_user.organization_id))
    office = result.scalar_one_or_none()
    if not office:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found or not deleted")
    office.is_deleted = False
    office.deleted_at = None
    await db.commit()
    await log_activity(db, user=current_user, action="updated", entity_type="office", entity_id=office_id, entity_label=office.location_name)
    result = await db.execute(
        select(Office).options(joinedload(Office.manager)).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id)
    )
    return OfficeResponse.model_validate(result.scalar_one(), from_attributes=True)


@router.get("/{office_id}/vendors", response_model=list[VendorResponse])
async def get_office_vendors(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all vendors assigned to a specific office."""
    office_result = await db.execute(
        select(Office).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id)
    )
    if not office_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")

    stmt = (
        select(Vendor)
        .options(joinedload(Vendor.offices))
        .join(vendor_offices)
        .where(vendor_offices.c.office_id == office_id, Vendor.is_deleted.is_(False))
        .order_by(Vendor.company_name)
    )
    result = await db.execute(stmt)
    vendors = result.scalars().unique().all()
    return [VendorResponse.model_validate(v, from_attributes=True) for v in vendors]


@router.get("/{office_id}/hvac-contracts", response_model=list[HvacContractResponse])
async def get_office_hvac_contracts(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all HVAC contracts assigned to a specific office."""
    office_result = await db.execute(
        select(Office).where(Office.id == office_id, Office.is_deleted.is_(False), Office.organization_id == current_user.organization_id)
    )
    if not office_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")

    stmt = (
        select(HvacContract)
        .options(
            joinedload(HvacContract.manager),
            joinedload(HvacContract.details),
        )
        .where(HvacContract.office_id == office_id, HvacContract.is_deleted.is_(False))
        .order_by(HvacContract.hvac_company)
    )
    result = await db.execute(stmt)
    contracts = result.scalars().unique().all()
    return [HvacContractResponse.model_validate(c, from_attributes=True) for c in contracts]

import math
import uuid
import csv
import io
from datetime import date, timedelta, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from icalendar import Calendar, Event
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.hvac_contract import HvacContract, HvacOfficeDetail
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.hvac_contract import (
    HvacContractCreate,
    HvacContractResponse,
    HvacContractUpdate,
)
from app.services.activity_service import log_activity, compute_changes
from app.utils.sorting import apply_sorting

router = APIRouter()


@router.get("/export")
async def export_hvac_contracts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HvacContract).options(joinedload(HvacContract.manager)).where(HvacContract.is_deleted.is_(False)).where(HvacContract.organization_id == current_user.organization_id).order_by(HvacContract.office_number)
    )
    contracts = result.scalars().unique().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Office #", "Office Name", "HVAC Company", "Frequency", "Last Serviced", "Next Service", "Manager", "Landlord Handles"])
    for c in contracts:
        writer.writerow([
            c.office_number, c.office_name, c.hvac_company, c.frequency,
            c.last_serviced_date, c.next_service_date,
            c.manager.name if c.manager else "", "Yes" if c.landlord_handles else "No",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hvac_contracts.csv"},
    )


@router.get("/export/ical")
async def export_hvac_contracts_ical(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HvacContract).where(HvacContract.is_deleted.is_(False)).where(HvacContract.organization_id == current_user.organization_id)
    )
    contracts = result.scalars().all()

    cal = Calendar()
    cal.add("prodid", "-//Portfolio Desk//HVAC//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "HVAC Service Dates")

    for contract in contracts:
        if contract.next_service_date:
            svc = contract.next_service_date
            if isinstance(svc, datetime):
                svc = svc.date()
            event = Event()
            event.add("summary", f"HVAC Service Due: {contract.hvac_company} — {contract.office_name or ''}")
            event.add("dtstart", svc)
            event.add("dtend", svc + timedelta(days=1))
            event.add("description", f"Office #{contract.office_number}")
            event["uid"] = f"hvac-{contract.id}@officemanager"
            cal.add_component(event)

    return StreamingResponse(
        iter([cal.to_ical()]),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=hvac-service-dates.ics"},
    )


@router.get("/due", response_model=list[HvacContractResponse])
async def contracts_due(
    days: int = Query(default=30, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cutoff = date.today() + timedelta(days=days)
    result = await db.execute(
        select(HvacContract)
        .options(joinedload(HvacContract.manager), joinedload(HvacContract.details))
        .where(HvacContract.is_deleted.is_(False))
        .where(HvacContract.next_service_date.is_not(None))
        .where(HvacContract.next_service_date <= cutoff)
        .where(HvacContract.landlord_handles == False)  # noqa: E712
        .where(HvacContract.organization_id == current_user.organization_id)
        .order_by(HvacContract.next_service_date)
    )
    return [HvacContractResponse.model_validate(c, from_attributes=True) for c in result.scalars().unique().all()]


@router.get("", response_model=PaginatedResponse[HvacContractResponse])
async def list_hvac_contracts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    manager_id: uuid.UUID | None = Query(default=None),
    frequency: str | None = Query(default=None),
    landlord_handles: bool | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = select(HvacContract).options(
        joinedload(HvacContract.manager), joinedload(HvacContract.details)
    ).where(HvacContract.is_deleted.is_(False))
    base = base.where(HvacContract.organization_id == current_user.organization_id)

    if manager_id is not None:
        base = base.where(HvacContract.manager_id == manager_id)
    if frequency is not None:
        base = base.where(HvacContract.frequency == frequency)
    if landlord_handles is not None:
        base = base.where(HvacContract.landlord_handles == landlord_handles)
    if search:
        term = f"%{search}%"
        base = base.where(
            or_(
                HvacContract.hvac_company.ilike(term),
                HvacContract.contact.ilike(term),
                HvacContract.office_name.ilike(term),
            )
        )

    count_stmt = select(func.count()).select_from(
        base.with_only_columns(HvacContract.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _HVAC_SORT_COLS = {
        "office_number": HvacContract.office_number,
        "office_name": HvacContract.office_name,
        "hvac_company": HvacContract.hvac_company,
        "next_service_date": HvacContract.next_service_date,
        "frequency": HvacContract.frequency,
    }
    stmt = apply_sorting(base, sort_by, sort_order, _HVAC_SORT_COLS, [HvacContract.office_number])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    contracts = result.scalars().unique().all()

    return PaginatedResponse(
        items=[HvacContractResponse.model_validate(c, from_attributes=True) for c in contracts],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{contract_id}", response_model=HvacContractResponse)
async def get_hvac_contract(
    contract_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HvacContract)
        .options(joinedload(HvacContract.manager), joinedload(HvacContract.details))
        .where(HvacContract.id == contract_id, HvacContract.is_deleted.is_(False), HvacContract.organization_id == current_user.organization_id)
    )
    contract = result.unique().scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC contract not found")
    return HvacContractResponse.model_validate(contract, from_attributes=True)


@router.post("", response_model=HvacContractResponse, status_code=status.HTTP_201_CREATED)
async def create_hvac_contract(
    payload: HvacContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    contract = HvacContract(**payload.model_dump(), organization_id=current_user.organization_id)
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    await log_activity(db, user=current_user, action="created", entity_type="hvac_contract", entity_id=contract.id, entity_label=contract.office_name or contract.hvac_company or f"Office #{contract.office_number}")

    result = await db.execute(
        select(HvacContract)
        .options(joinedload(HvacContract.manager), joinedload(HvacContract.details))
        .where(HvacContract.id == contract.id)
    )
    return HvacContractResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.put("/{contract_id}", response_model=HvacContractResponse)
async def update_hvac_contract(
    contract_id: uuid.UUID,
    payload: HvacContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    org_id = current_user.organization_id
    result = await db.execute(select(HvacContract).where(HvacContract.id == contract_id, HvacContract.is_deleted.is_(False), HvacContract.organization_id == current_user.organization_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC contract not found")

    update_data = payload.model_dump(exclude_unset=True)
    old_values = {k: getattr(contract, k) for k in update_data}
    for field, value in update_data.items():
        setattr(contract, field, value)

    await db.commit()
    changes = compute_changes(old_values, update_data)
    await log_activity(db, user=current_user, action="updated", entity_type="hvac_contract", entity_id=contract.id, entity_label=contract.office_name or contract.hvac_company or f"Office #{contract.office_number}", changes=changes)

    result = await db.execute(
        select(HvacContract)
        .options(joinedload(HvacContract.manager), joinedload(HvacContract.details))
        .where(
            HvacContract.id == contract_id,
            HvacContract.is_deleted.is_(False),
            HvacContract.organization_id == org_id,
        )
    )
    return HvacContractResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hvac_contract(
    contract_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(HvacContract).where(HvacContract.id == contract_id, HvacContract.is_deleted.is_(False), HvacContract.organization_id == current_user.organization_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC contract not found")
    label = contract.office_name or contract.hvac_company or f"Office #{contract.office_number}"
    contract.is_deleted = True
    contract.deleted_at = _utcnow()
    await db.commit()
    await log_activity(db, user=current_user, action="deleted", entity_type="hvac_contract", entity_id=contract_id, entity_label=label)


@router.patch("/{contract_id}/restore", response_model=HvacContractResponse)
async def restore_hvac_contract(
    contract_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    org_id = current_user.organization_id
    result = await db.execute(select(HvacContract).where(HvacContract.id == contract_id, HvacContract.is_deleted.is_(True), HvacContract.organization_id == current_user.organization_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HVAC contract not found or not deleted")
    contract.is_deleted = False
    contract.deleted_at = None
    await db.commit()
    label = contract.office_name or contract.hvac_company or f"Office #{contract.office_number}"
    await log_activity(db, user=current_user, action="updated", entity_type="hvac_contract", entity_id=contract_id, entity_label=label)
    result = await db.execute(
        select(HvacContract)
        .options(joinedload(HvacContract.manager), joinedload(HvacContract.details))
        .where(
            HvacContract.id == contract_id,
            HvacContract.is_deleted.is_(False),
            HvacContract.organization_id == org_id,
        )
    )
    return HvacContractResponse.model_validate(result.unique().scalar_one(), from_attributes=True)

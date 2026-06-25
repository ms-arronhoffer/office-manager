import math
import uuid
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.landlord import Landlord, LandlordAdditionalName, LandlordContact, landlord_offices
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.landlord import (
    LandlordCreate,
    LandlordContactCreate,
    LandlordContactResponse,
    LandlordContactUpdate,
    LandlordResponse,
    LandlordUpdate,
)
from app.services.activity_service import log_activity, compute_changes
from app.utils.search_vectors import update_search_vector
from app.utils.sorting import apply_sorting

router = APIRouter()


async def _sync_offices(db: AsyncSession, landlord_id: uuid.UUID, office_ids: list[uuid.UUID]) -> None:
    """Replace the set of offices owned by a landlord."""
    await db.execute(delete(landlord_offices).where(landlord_offices.c.landlord_id == landlord_id))
    for oid in office_ids:
        await db.execute(landlord_offices.insert().values(landlord_id=landlord_id, office_id=oid))


@router.get("/export")
async def export_landlords(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Landlord).where(Landlord.is_deleted.is_(False)).where(Landlord.organization_id == current_user.organization_id).order_by(Landlord.landlord_company)
    )
    landlords = result.scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ERN", "Company", "Office Name", "Contact", "Email", "Phone", "Address", "Vendor ID"])
    for l in landlords:
        writer.writerow([
            l.ern, l.landlord_company, l.office_name, l.contact_name,
            l.contact_email, l.contact_phone, l.address, l.vendor_id,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=landlords.csv"},
    )


@router.get("", response_model=PaginatedResponse[LandlordResponse])
async def list_landlords(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    search: str | None = Query(default=None),
    office_id: uuid.UUID | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = select(Landlord).options(
        joinedload(Landlord.additional_names),
        joinedload(Landlord.contacts),
        joinedload(Landlord.owned_offices),
        joinedload(Landlord.management_company_ref),
    ).where(Landlord.is_deleted.is_(False))
    base = base.where(Landlord.organization_id == current_user.organization_id)

    if office_id is not None:
        # Match landlords linked to the office either via the legacy single
        # office_id column or via the many-to-many owned-offices association.
        owned_subq = select(landlord_offices.c.landlord_id).where(
            landlord_offices.c.office_id == office_id
        )
        base = base.where(
            or_(
                Landlord.office_id == office_id,
                Landlord.id.in_(owned_subq),
            )
        )

    if search:
        term = f"%{search}%"
        base = base.where(
            or_(
                Landlord.landlord_company.ilike(term),
                Landlord.contact_name.ilike(term),
                Landlord.office_name.ilike(term),
                Landlord.ern.ilike(term),
            )
        )

    count_stmt = select(func.count()).select_from(
        base.with_only_columns(Landlord.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _LANDLORD_SORT_COLS = {
        "landlord_company": Landlord.landlord_company,
        "contact_name": Landlord.contact_name,
        "office_name": Landlord.office_name,
        "ern": Landlord.ern,
    }
    stmt = apply_sorting(base, sort_by, sort_order, _LANDLORD_SORT_COLS, [Landlord.landlord_company, Landlord.contact_name])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    landlords = result.scalars().unique().all()

    return PaginatedResponse(
        items=[LandlordResponse.model_validate(l, from_attributes=True) for l in landlords],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{landlord_id}", response_model=LandlordResponse)
async def get_landlord(
    landlord_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Landlord)
        .options(joinedload(Landlord.additional_names), joinedload(Landlord.contacts), joinedload(Landlord.owned_offices), joinedload(Landlord.management_company_ref))
        .where(Landlord.id == landlord_id, Landlord.is_deleted.is_(False), Landlord.organization_id == current_user.organization_id)
    )
    landlord = result.unique().scalar_one_or_none()
    if not landlord:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landlord not found")
    return LandlordResponse.model_validate(landlord, from_attributes=True)


@router.post("", response_model=LandlordResponse, status_code=status.HTTP_201_CREATED)
async def create_landlord(
    payload: LandlordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    data = payload.model_dump(exclude={"office_ids"})
    landlord = Landlord(**data, organization_id=current_user.organization_id)
    db.add(landlord)
    # Flush to assign landlord.id before syncing the office associations.
    await db.flush()

    if payload.office_ids:
        await _sync_offices(db, landlord.id, payload.office_ids)

    await db.commit()
    await db.refresh(landlord)
    await log_activity(db, user=current_user, action="created", entity_type="landlord", entity_id=landlord.id, entity_label=landlord.landlord_company or landlord.contact_name or "Landlord")
    try:
        await update_search_vector(db, "landlords", landlord.id)
    except Exception:
        pass

    result = await db.execute(
        select(Landlord)
        .options(joinedload(Landlord.additional_names), joinedload(Landlord.contacts), joinedload(Landlord.owned_offices), joinedload(Landlord.management_company_ref))
        .where(Landlord.id == landlord.id)
    )
    return LandlordResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.put("/{landlord_id}", response_model=LandlordResponse)
async def update_landlord(
    landlord_id: uuid.UUID,
    payload: LandlordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(Landlord).where(Landlord.id == landlord_id, Landlord.is_deleted.is_(False), Landlord.organization_id == current_user.organization_id))
    landlord = result.scalar_one_or_none()
    if not landlord:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landlord not found")

    update_data = payload.model_dump(exclude_unset=True, exclude={"office_ids"})
    old_values = {k: getattr(landlord, k) for k in update_data}
    for field, value in update_data.items():
        setattr(landlord, field, value)

    if payload.office_ids is not None:
        await _sync_offices(db, landlord_id, payload.office_ids)

    await db.commit()
    changes = compute_changes(old_values, update_data)
    await log_activity(db, user=current_user, action="updated", entity_type="landlord", entity_id=landlord.id, entity_label=landlord.landlord_company or landlord.contact_name or "Landlord", changes=changes)
    try:
        await update_search_vector(db, "landlords", landlord.id)
    except Exception:
        pass

    result = await db.execute(
        select(Landlord)
        .options(joinedload(Landlord.additional_names), joinedload(Landlord.contacts), joinedload(Landlord.owned_offices), joinedload(Landlord.management_company_ref))
        .where(Landlord.id == landlord_id, Landlord.is_deleted.is_(False))
    )
    return LandlordResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.delete("/{landlord_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_landlord(
    landlord_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Landlord).where(Landlord.id == landlord_id, Landlord.is_deleted.is_(False), Landlord.organization_id == current_user.organization_id))
    landlord = result.scalar_one_or_none()
    if not landlord:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landlord not found")
    label = landlord.landlord_company or landlord.contact_name or "Landlord"
    landlord.is_deleted = True
    landlord.deleted_at = _utcnow()
    await db.commit()
    await log_activity(db, user=current_user, action="deleted", entity_type="landlord", entity_id=landlord_id, entity_label=label)


@router.patch("/{landlord_id}/restore", response_model=LandlordResponse)
async def restore_landlord(
    landlord_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Landlord).where(Landlord.id == landlord_id, Landlord.is_deleted.is_(True), Landlord.organization_id == current_user.organization_id))
    landlord = result.scalar_one_or_none()
    if not landlord:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landlord not found or not deleted")
    landlord.is_deleted = False
    landlord.deleted_at = None
    await db.commit()
    label = landlord.landlord_company or landlord.contact_name or "Landlord"
    await log_activity(db, user=current_user, action="updated", entity_type="landlord", entity_id=landlord_id, entity_label=label)
    result = await db.execute(
        select(Landlord)
        .options(joinedload(Landlord.additional_names), joinedload(Landlord.contacts), joinedload(Landlord.owned_offices), joinedload(Landlord.management_company_ref))
        .where(Landlord.id == landlord_id, Landlord.is_deleted.is_(False))
    )
    return LandlordResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


# ---------------------------------------------------------------------------
# Contacts sub-resource
# ---------------------------------------------------------------------------

@router.post(
    "/{landlord_id}/contacts",
    response_model=LandlordContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_contact(
    landlord_id: uuid.UUID,
    payload: LandlordContactCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(Landlord).where(Landlord.id == landlord_id, Landlord.is_deleted.is_(False)))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Landlord not found")

    contact = LandlordContact(landlord_id=landlord_id, **payload.model_dump())
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return LandlordContactResponse.model_validate(contact, from_attributes=True)


@router.put(
    "/{landlord_id}/contacts/{contact_id}",
    response_model=LandlordContactResponse,
)
async def update_contact(
    landlord_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: LandlordContactUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(LandlordContact).where(
            LandlordContact.id == contact_id,
            LandlordContact.landlord_id == landlord_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    await db.commit()
    await db.refresh(contact)
    return LandlordContactResponse.model_validate(contact, from_attributes=True)


@router.delete(
    "/{landlord_id}/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contact(
    landlord_id: uuid.UUID,
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(LandlordContact).where(
            LandlordContact.id == contact_id,
            LandlordContact.landlord_id == landlord_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    await db.delete(contact)
    await db.commit()

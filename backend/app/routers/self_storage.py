"""Self-storage (org-as-operator) API router — ``/api/v1/self-storage``.

The third primary category alongside commercial and residential. Manages
storage units at a facility (Office), rental agreements with resident tenants,
reservations, rate plans, the delinquency/lien/auction workflow, and recurring
billing posted through the shared AR/GL.

Reads are open to any authenticated org user; writes require ``admin``/``editor``
and destructive deletes require ``admin`` (mirroring the leasing router). Amounts
are USD-only for now.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.customer_invoice import CustomerInvoice
from app.models.resident import Resident
from app.models.self_storage import (
    STORAGE_AGREEMENT_STATUSES,
    STORAGE_LIEN_STEPS,
    STORAGE_OCCUPANT_ROLES,
    STORAGE_RESERVATION_STATUSES,
    STORAGE_UNIT_STATUSES,
    STORAGE_UNIT_TYPES,
    StorageAgreement,
    StorageAgreementOccupant,
    StorageCharge,
    StorageFacility,
    StorageLienEvent,
    StorageManager,
    StorageRatePlan,
    StorageReservation,
    StorageUnit,
)
from app.models.user import User
from app.services import self_storage_service as svc
from app.services.self_storage_service import SelfStorageError
from app.utils.tenant_scope import load_or_404
from sqlalchemy.exc import IntegrityError

router = APIRouter()

Editor = require_role("admin", "editor")
Admin = require_role("admin")
Finance = require_role("admin", "accountant")


def _fail(exc: SelfStorageError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Schemas — Facilities (the self-storage "Property")
# ---------------------------------------------------------------------------

class StorageManagerBase(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None


class StorageManagerCreate(StorageManagerBase):
    pass


class StorageManagerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class StorageManagerResponse(StorageManagerBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    model_config = {"from_attributes": True}


class StorageFacilityBase(BaseModel):
    name: str
    facility_number: int | None = None
    code: str | None = None
    is_active: bool = True
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    email: str | None = None
    manager_id: uuid.UUID | None = None
    manager_name: str | None = None
    gate_hours: str | None = None
    access_hours: str | None = None
    total_units: int | None = None
    notes: str | None = None


class StorageFacilityCreate(StorageFacilityBase):
    pass


class StorageFacilityUpdate(BaseModel):
    name: str | None = None
    facility_number: int | None = None
    code: str | None = None
    is_active: bool | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    email: str | None = None
    manager_id: uuid.UUID | None = None
    manager_name: str | None = None
    gate_hours: str | None = None
    access_hours: str | None = None
    total_units: int | None = None
    notes: str | None = None


class StorageFacilityResponse(StorageFacilityBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    manager: StorageManagerResponse | None = None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Schemas — Units
# ---------------------------------------------------------------------------

class StorageUnitBase(BaseModel):
    facility_id: uuid.UUID | None = None
    unit_number: str
    building: str | None = None
    row: str | None = None
    floor: str | None = None
    width_ft: Decimal | None = None
    length_ft: Decimal | None = None
    height_ft: Decimal | None = None
    square_feet: Decimal | None = None
    cubic_feet: Decimal | None = None
    size_label: str | None = None
    size_tier: str | None = None
    unit_type: str = "interior"
    climate_controlled: bool = False
    has_power: bool = False
    is_alarmed: bool = False
    drive_up_access: bool = False
    ground_floor: bool = False
    elevator_access: bool = False
    access_24hr: bool = False
    street_rate: Decimal | None = None
    standard_rate: Decimal | None = None
    in_place_rate: Decimal | None = None
    promo_rate: Decimal | None = None
    status: str = "available"
    lock_state: str = "unlocked"
    gate_zone: str | None = None
    notes: str | None = None


class StorageUnitCreate(StorageUnitBase):
    pass


class StorageUnitUpdate(BaseModel):
    facility_id: uuid.UUID | None = None
    unit_number: str | None = None
    building: str | None = None
    row: str | None = None
    floor: str | None = None
    width_ft: Decimal | None = None
    length_ft: Decimal | None = None
    height_ft: Decimal | None = None
    square_feet: Decimal | None = None
    cubic_feet: Decimal | None = None
    size_label: str | None = None
    size_tier: str | None = None
    unit_type: str | None = None
    climate_controlled: bool | None = None
    has_power: bool | None = None
    is_alarmed: bool | None = None
    drive_up_access: bool | None = None
    ground_floor: bool | None = None
    elevator_access: bool | None = None
    access_24hr: bool | None = None
    street_rate: Decimal | None = None
    standard_rate: Decimal | None = None
    in_place_rate: Decimal | None = None
    promo_rate: Decimal | None = None
    status: str | None = None
    lock_state: str | None = None
    gate_zone: str | None = None
    notes: str | None = None


class StorageUnitResponse(StorageUnitBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    currency: str
    model_config = {"from_attributes": True}


class StorageUnitBulkCreate(BaseModel):
    facility_id: uuid.UUID | None = None
    count: int
    start_number: int = 1
    prefix: str = ""
    size_tier: str | None = None
    size_label: str | None = None
    unit_type: str = "interior"
    climate_controlled: bool = False
    street_rate: Decimal | None = None
    standard_rate: Decimal | None = None


# ---------------------------------------------------------------------------
# Schemas — Agreements
# ---------------------------------------------------------------------------

class OccupantInput(BaseModel):
    resident_id: uuid.UUID
    role: str = "primary"
    is_primary: bool = False


class OccupantResponse(BaseModel):
    id: uuid.UUID
    resident_id: uuid.UUID
    role: str
    is_primary: bool
    model_config = {"from_attributes": True}


class StorageAgreementBase(BaseModel):
    unit_id: uuid.UUID
    facility_id: uuid.UUID | None = None
    name: str | None = None
    status: str = "draft"
    rent_amount: Decimal | None = None
    security_deposit: Decimal | None = None
    admin_fee: Decimal | None = None
    billing_day: int | None = None
    billing_cycle: str = "monthly"
    autopay_enabled: bool = False
    autopay_method: str | None = None
    insurance_plan: str | None = None
    insurance_coverage: Decimal | None = None
    insurance_premium: Decimal | None = None
    gate_code: str | None = None
    late_fee_amount: Decimal | None = None
    late_fee_grace_days: int | None = None
    move_in_date: date | None = None
    move_out_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None


class StorageAgreementCreate(StorageAgreementBase):
    occupants: list[OccupantInput] = []


class StorageAgreementUpdate(BaseModel):
    facility_id: uuid.UUID | None = None
    name: str | None = None
    status: str | None = None
    rent_amount: Decimal | None = None
    security_deposit: Decimal | None = None
    admin_fee: Decimal | None = None
    billing_day: int | None = None
    billing_cycle: str | None = None
    autopay_enabled: bool | None = None
    autopay_method: str | None = None
    insurance_plan: str | None = None
    insurance_coverage: Decimal | None = None
    insurance_premium: Decimal | None = None
    gate_code: str | None = None
    late_fee_amount: Decimal | None = None
    late_fee_grace_days: int | None = None
    move_in_date: date | None = None
    move_out_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = None
    occupants: list[OccupantInput] | None = None


class StorageAgreementResponse(StorageAgreementBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    currency: str
    occupants: list[OccupantResponse] = []
    model_config = {"from_attributes": True}


class MoveInRequest(BaseModel):
    move_in_date: date | None = None


class MoveOutRequest(BaseModel):
    move_out_date: date | None = None


class ChangeRateRequest(BaseModel):
    new_rate: Decimal


class LienStepRequest(BaseModel):
    step: str
    event_date: date | None = None
    amount_due: Decimal | None = None
    notes: str | None = None
    details: dict | None = None


class LienEventResponse(BaseModel):
    id: uuid.UUID
    agreement_id: uuid.UUID
    step: str
    event_date: date
    amount_due: Decimal | None
    notes: str | None
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Schemas — Reservations / Rate plans / Charges
# ---------------------------------------------------------------------------

class ReservationBase(BaseModel):
    facility_id: uuid.UUID | None = None
    unit_id: uuid.UUID | None = None
    resident_id: uuid.UUID | None = None
    prospect_name: str | None = None
    prospect_email: str | None = None
    prospect_phone: str | None = None
    size_tier: str | None = None
    quoted_rate: Decimal | None = None
    status: str = "held"
    hold_until: date | None = None
    notes: str | None = None


class ReservationResponse(ReservationBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    model_config = {"from_attributes": True}


class RatePlanBase(BaseModel):
    facility_id: uuid.UUID | None = None
    size_tier: str
    name: str | None = None
    street_rate: Decimal | None = None
    standard_rate: Decimal | None = None
    increase_effective_date: date | None = None
    increase_amount: Decimal | None = None
    increase_percent: Decimal | None = None
    active: bool = True
    notes: str | None = None


class RatePlanResponse(RatePlanBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    currency: str
    model_config = {"from_attributes": True}


class ChargeBase(BaseModel):
    storage_agreement_id: uuid.UUID
    charge_type: str = "rent"
    description: str | None = None
    amount: Decimal
    frequency: str = "monthly"
    day_of_month: int = 1
    start_date: date | None = None
    end_date: date | None = None
    grace_days: int = 5
    late_fee_type: str = "none"
    late_fee_amount: Decimal | None = None
    revenue_account_code: str = "4100"
    active: bool = True


class ChargeResponse(ChargeBase):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    currency: str
    last_billed_period: date | None
    model_config = {"from_attributes": True}


class PaymentRequest(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal
    method: str = "ach"
    receipt_date: date | None = None
    reference: str | None = None


# ---------------------------------------------------------------------------
# Managers (self-storage — its own data set, mirroring the commercial Manager)
# ---------------------------------------------------------------------------

async def _resolve_manager(
    db: AsyncSession, manager_id: uuid.UUID | None, org_id
) -> StorageManager | None:
    """Validate a manager id belongs to the org, returning the manager or None."""
    if manager_id is None:
        return None
    return await load_or_404(
        db, StorageManager, manager_id, org_id, detail="Manager not found"
    )


@router.get("/managers", response_model=list[StorageManagerResponse])
async def list_storage_managers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(StorageManager)
        .where(StorageManager.organization_id == current_user.organization_id)
        .order_by(StorageManager.name)
    )
    return (await db.execute(stmt)).scalars().all()


@router.post(
    "/managers",
    response_model=StorageManagerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_storage_manager(
    payload: StorageManagerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Manager name is required")
    manager = StorageManager(
        organization_id=current_user.organization_id,
        name=name,
        email=(payload.email or None),
        phone=(payload.phone or None),
    )
    db.add(manager)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A manager named '{name}' already exists.",
        )
    await db.refresh(manager)
    return manager


@router.patch("/managers/{manager_id}", response_model=StorageManagerResponse)
async def update_storage_manager(
    manager_id: uuid.UUID,
    payload: StorageManagerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    manager = await load_or_404(
        db, StorageManager, manager_id, current_user.organization_id,
        detail="Manager not found",
    )
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Manager name is required")
        data["name"] = name
    for field, value in data.items():
        setattr(manager, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A manager with that name already exists.",
        )
    await db.refresh(manager)
    return manager


@router.delete("/managers/{manager_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage_manager(
    manager_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = current_user.organization_id
    manager = await load_or_404(
        db, StorageManager, manager_id, org_id, detail="Manager not found"
    )
    # Detach the manager from any facilities so the FK does not block deletion.
    facilities = (
        await db.execute(
            select(StorageFacility).where(
                StorageFacility.manager_id == manager_id,
                StorageFacility.organization_id == org_id,
            )
        )
    ).scalars().all()
    for facility in facilities:
        facility.manager_id = None
    await db.delete(manager)
    await db.commit()


# ---------------------------------------------------------------------------
# Facilities (the self-storage "Property")
# ---------------------------------------------------------------------------

@router.get("/facilities", response_model=list[StorageFacilityResponse])
async def list_facilities(
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(StorageFacility)
        .where(
            StorageFacility.organization_id == current_user.organization_id,
            StorageFacility.is_deleted.is_(False),
        )
        .options(selectinload(StorageFacility.manager))
    )
    if is_active is not None:
        stmt = stmt.where(StorageFacility.is_active.is_(is_active))
    if q:
        stmt = stmt.where(StorageFacility.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(StorageFacility.name)
    return (await db.execute(stmt)).scalars().all()


async def _load_facility(
    db: AsyncSession, facility_id: uuid.UUID, org_id
) -> StorageFacility:
    facility = await load_or_404(
        db, StorageFacility, facility_id, org_id,
        extra_filters=[StorageFacility.is_deleted.is_(False)],
        detail="Facility not found",
    )
    await db.refresh(facility, attribute_names=["manager"])
    return facility


@router.get("/facilities/{facility_id}", response_model=StorageFacilityResponse)
async def get_facility(
    facility_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_facility(db, facility_id, current_user.organization_id)


@router.post("/facilities", response_model=StorageFacilityResponse, status_code=status.HTTP_201_CREATED)
async def create_facility(
    payload: StorageFacilityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Property name is required")
    data = payload.model_dump()
    data["name"] = name
    manager = await _resolve_manager(db, payload.manager_id, org_id)
    # Keep the legacy free-text manager_name in sync with the assigned manager.
    if manager is not None:
        data["manager_name"] = manager.name
    facility = StorageFacility(organization_id=org_id, **data)
    db.add(facility)
    await db.commit()
    return await _load_facility(db, facility.id, org_id)


@router.patch("/facilities/{facility_id}", response_model=StorageFacilityResponse)
async def update_facility(
    facility_id: uuid.UUID,
    payload: StorageFacilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    facility = await load_or_404(
        db, StorageFacility, facility_id, org_id,
        extra_filters=[StorageFacility.is_deleted.is_(False)],
        detail="Facility not found",
    )
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Property name is required")
        data["name"] = name
    if "manager_id" in data:
        manager = await _resolve_manager(db, data["manager_id"], org_id)
        # Sync the free-text name; clearing the manager clears the cached name
        # unless the caller explicitly provided one.
        if manager is not None:
            data.setdefault("manager_name", manager.name)
        elif "manager_name" not in data:
            data["manager_name"] = None
    for field, value in data.items():
        setattr(facility, field, value)
    await db.commit()
    return await _load_facility(db, facility_id, org_id)


@router.delete("/facilities/{facility_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_facility(
    facility_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    facility = await load_or_404(
        db, StorageFacility, facility_id, current_user.organization_id,
        extra_filters=[StorageFacility.is_deleted.is_(False)],
        detail="Facility not found",
    )
    facility.is_deleted = True
    await db.commit()


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@router.get("/units", response_model=list[StorageUnitResponse])
async def list_units(
    facility_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    size_tier: str | None = Query(default=None),
    unit_type: str | None = Query(default=None),
    climate_controlled: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(StorageUnit).where(
        StorageUnit.organization_id == current_user.organization_id,
        StorageUnit.is_deleted.is_(False),
    )
    if facility_id is not None:
        stmt = stmt.where(StorageUnit.facility_id == facility_id)
    if status_filter:
        stmt = stmt.where(StorageUnit.status == status_filter)
    if size_tier:
        stmt = stmt.where(StorageUnit.size_tier == size_tier)
    if unit_type:
        stmt = stmt.where(StorageUnit.unit_type == unit_type)
    if climate_controlled is not None:
        stmt = stmt.where(StorageUnit.climate_controlled.is_(climate_controlled))
    if q:
        stmt = stmt.where(StorageUnit.unit_number.ilike(f"%{q}%"))
    stmt = stmt.order_by(StorageUnit.unit_number)
    return (await db.execute(stmt)).scalars().all()


@router.get("/units/{unit_id}", response_model=StorageUnitResponse)
async def get_unit(
    unit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await load_or_404(
        db, StorageUnit, unit_id, current_user.organization_id,
        extra_filters=[StorageUnit.is_deleted.is_(False)],
        detail="Storage unit not found",
    )


def _validate_unit_enums(unit_type: str | None, status_value: str | None) -> None:
    if unit_type is not None and unit_type not in STORAGE_UNIT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid unit_type: {unit_type}")
    if status_value is not None and status_value not in STORAGE_UNIT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {status_value}")


@router.post("/units", response_model=StorageUnitResponse, status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: StorageUnitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    _validate_unit_enums(payload.unit_type, payload.status)
    unit = StorageUnit(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(unit)
    await db.commit()
    await db.refresh(unit)
    return unit


@router.post("/units/bulk", response_model=list[StorageUnitResponse], status_code=status.HTTP_201_CREATED)
async def bulk_create_units(
    payload: StorageUnitBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    if payload.count < 1 or payload.count > 500:
        raise HTTPException(status_code=422, detail="count must be between 1 and 500")
    _validate_unit_enums(payload.unit_type, None)
    units: list[StorageUnit] = []
    for i in range(payload.count):
        number = payload.start_number + i
        units.append(
            StorageUnit(
                organization_id=current_user.organization_id,
                facility_id=payload.facility_id,
                unit_number=f"{payload.prefix}{number}",
                size_tier=payload.size_tier,
                size_label=payload.size_label,
                unit_type=payload.unit_type,
                climate_controlled=payload.climate_controlled,
                street_rate=payload.street_rate,
                standard_rate=payload.standard_rate,
            )
        )
    db.add_all(units)
    await db.commit()
    for u in units:
        await db.refresh(u)
    return units


@router.patch("/units/{unit_id}", response_model=StorageUnitResponse)
async def update_unit(
    unit_id: uuid.UUID,
    payload: StorageUnitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    unit = await load_or_404(
        db, StorageUnit, unit_id, current_user.organization_id,
        extra_filters=[StorageUnit.is_deleted.is_(False)],
        detail="Storage unit not found",
    )
    data = payload.model_dump(exclude_unset=True)
    _validate_unit_enums(data.get("unit_type"), data.get("status"))
    for field, value in data.items():
        setattr(unit, field, value)
    await db.commit()
    await db.refresh(unit)
    return unit


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(
    unit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    unit = await load_or_404(
        db, StorageUnit, unit_id, current_user.organization_id,
        extra_filters=[StorageUnit.is_deleted.is_(False)],
        detail="Storage unit not found",
    )
    unit.is_deleted = True
    await db.commit()


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------

async def _build_occupants(
    db: AsyncSession, org_id, occupants: list[OccupantInput]
) -> list[StorageAgreementOccupant]:
    built: list[StorageAgreementOccupant] = []
    for occ in occupants:
        # Ensure the resident belongs to the org.
        await load_or_404(
            db, Resident, occ.resident_id, org_id,
            extra_filters=[Resident.is_deleted.is_(False)],
            detail="Resident not found",
        )
        if occ.role not in STORAGE_OCCUPANT_ROLES:
            raise HTTPException(status_code=422, detail=f"Invalid role: {occ.role}")
        built.append(
            StorageAgreementOccupant(
                resident_id=occ.resident_id,
                role=occ.role,
                is_primary=occ.is_primary,
            )
        )
    return built


async def _load_agreement(db: AsyncSession, agreement_id: uuid.UUID, org_id) -> StorageAgreement:
    agreement = await load_or_404(
        db, StorageAgreement, agreement_id, org_id,
        extra_filters=[StorageAgreement.is_deleted.is_(False)],
        detail="Storage agreement not found",
    )
    await db.refresh(agreement, attribute_names=["occupants"])
    return agreement


@router.get("/agreements", response_model=list[StorageAgreementResponse])
async def list_agreements(
    unit_id: uuid.UUID | None = Query(default=None),
    facility_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(StorageAgreement)
        .where(
            StorageAgreement.organization_id == current_user.organization_id,
            StorageAgreement.is_deleted.is_(False),
        )
        .options(selectinload(StorageAgreement.occupants))
    )
    if unit_id is not None:
        stmt = stmt.where(StorageAgreement.unit_id == unit_id)
    if facility_id is not None:
        stmt = stmt.where(StorageAgreement.facility_id == facility_id)
    if status_filter:
        stmt = stmt.where(StorageAgreement.status == status_filter)
    stmt = stmt.order_by(StorageAgreement.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/agreements/{agreement_id}", response_model=StorageAgreementResponse)
async def get_agreement(
    agreement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_agreement(db, agreement_id, current_user.organization_id)


@router.post("/agreements", response_model=StorageAgreementResponse, status_code=status.HTTP_201_CREATED)
async def create_agreement(
    payload: StorageAgreementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    if payload.status not in STORAGE_AGREEMENT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {payload.status}")
    # Validate unit belongs to org.
    unit = await load_or_404(
        db, StorageUnit, payload.unit_id, org_id,
        extra_filters=[StorageUnit.is_deleted.is_(False)],
        detail="Storage unit not found",
    )
    data = payload.model_dump(exclude={"occupants"})
    # An agreement belongs to a facility (like a commercial lease belongs to an
    # office). Default it from the unit's facility when the caller omits it, and
    # validate any explicitly-provided facility belongs to the org and matches
    # the unit's facility so agreements are not mis-filed.
    if data.get("facility_id") is None:
        data["facility_id"] = unit.facility_id
    else:
        await load_or_404(
            db, StorageFacility, data["facility_id"], org_id,
            extra_filters=[StorageFacility.is_deleted.is_(False)],
            detail="Facility not found",
        )
        if unit.facility_id is not None and data["facility_id"] != unit.facility_id:
            raise HTTPException(
                status_code=422,
                detail="The selected facility does not match the unit's facility.",
            )
    occupants = await _build_occupants(db, org_id, payload.occupants)
    try:
        if payload.status in ("active",):
            await svc.assert_no_active_overlap(db, payload.unit_id)
    except SelfStorageError as exc:
        raise _fail(exc)
    agreement = StorageAgreement(
        organization_id=org_id, occupants=occupants, **data
    )
    db.add(agreement)
    await db.flush()
    await svc.sync_unit_status(db, payload.unit_id, org_id)
    await db.commit()
    return await _load_agreement(db, agreement.id, org_id)


@router.patch("/agreements/{agreement_id}", response_model=StorageAgreementResponse)
async def update_agreement(
    agreement_id: uuid.UUID,
    payload: StorageAgreementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    agreement = await _load_agreement(db, agreement_id, org_id)
    data = payload.model_dump(exclude_unset=True, exclude={"occupants"})
    if "status" in data and data["status"] not in STORAGE_AGREEMENT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {data['status']}")
    for field, value in data.items():
        setattr(agreement, field, value)
    if payload.occupants is not None:
        agreement.occupants.clear()
        await db.flush()
        agreement.occupants = await _build_occupants(db, org_id, payload.occupants)
    await db.flush()
    await svc.sync_unit_status(db, agreement.unit_id, org_id)
    await db.commit()
    return await _load_agreement(db, agreement_id, org_id)


@router.delete("/agreements/{agreement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agreement(
    agreement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = current_user.organization_id
    agreement = await load_or_404(
        db, StorageAgreement, agreement_id, org_id,
        extra_filters=[StorageAgreement.is_deleted.is_(False)],
        detail="Storage agreement not found",
    )
    agreement.is_deleted = True
    await db.flush()
    await svc.sync_unit_status(db, agreement.unit_id, org_id)
    await db.commit()


@router.post("/agreements/{agreement_id}/move-in", response_model=StorageAgreementResponse)
async def move_in(
    agreement_id: uuid.UUID,
    payload: MoveInRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    try:
        await svc.move_in(
            db, current_user.organization_id, agreement_id,
            move_in_date=payload.move_in_date,
        )
    except SelfStorageError as exc:
        raise _fail(exc)
    return await _load_agreement(db, agreement_id, current_user.organization_id)


@router.post("/agreements/{agreement_id}/move-out", response_model=StorageAgreementResponse)
async def move_out(
    agreement_id: uuid.UUID,
    payload: MoveOutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    try:
        await svc.move_out(
            db, current_user.organization_id, agreement_id,
            move_out_date=payload.move_out_date,
        )
    except SelfStorageError as exc:
        raise _fail(exc)
    return await _load_agreement(db, agreement_id, current_user.organization_id)


@router.post("/agreements/{agreement_id}/change-rate", response_model=StorageAgreementResponse)
async def change_rate(
    agreement_id: uuid.UUID,
    payload: ChangeRateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    try:
        await svc.change_rate(
            db, current_user.organization_id, agreement_id, payload.new_rate
        )
    except SelfStorageError as exc:
        raise _fail(exc)
    return await _load_agreement(db, agreement_id, current_user.organization_id)


@router.get("/agreements/{agreement_id}/lien-events", response_model=list[LienEventResponse])
async def list_lien_events(
    agreement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _load_agreement(db, agreement_id, current_user.organization_id)
    stmt = (
        select(StorageLienEvent)
        .where(
            StorageLienEvent.agreement_id == agreement_id,
            StorageLienEvent.organization_id == current_user.organization_id,
        )
        .order_by(StorageLienEvent.event_date, StorageLienEvent.created_at)
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/agreements/{agreement_id}/lien-events", response_model=LienEventResponse, status_code=status.HTTP_201_CREATED)
async def record_lien_event(
    agreement_id: uuid.UUID,
    payload: LienStepRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    if payload.step not in STORAGE_LIEN_STEPS:
        raise HTTPException(status_code=422, detail=f"Invalid step: {payload.step}")
    try:
        event = await svc.record_lien_step(
            db, current_user.organization_id, agreement_id, payload.step,
            event_date=payload.event_date,
            amount_due=payload.amount_due,
            notes=payload.notes,
            details=payload.details,
            created_by_id=current_user.id,
        )
    except SelfStorageError as exc:
        raise _fail(exc)
    return event


# ---------------------------------------------------------------------------
# Tenants (residents linked to storage agreements)
# ---------------------------------------------------------------------------

@router.get("/tenants")
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List residents that occupy at least one storage agreement."""
    stmt = (
        select(Resident)
        .join(StorageAgreementOccupant, StorageAgreementOccupant.resident_id == Resident.id)
        .join(StorageAgreement, StorageAgreement.id == StorageAgreementOccupant.agreement_id)
        .where(
            Resident.organization_id == current_user.organization_id,
            Resident.is_deleted.is_(False),
            StorageAgreement.is_deleted.is_(False),
        )
        .distinct()
        .order_by(Resident.last_name, Resident.first_name)
    )
    residents = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "first_name": r.first_name,
            "last_name": r.last_name,
            "email": r.email,
            "phone": r.phone,
            "status": r.status,
        }
        for r in residents
    ]


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@router.get("/reservations", response_model=list[ReservationResponse])
async def list_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(StorageReservation).where(
        StorageReservation.organization_id == current_user.organization_id,
        StorageReservation.is_deleted.is_(False),
    )
    if status_filter:
        stmt = stmt.where(StorageReservation.status == status_filter)
    stmt = stmt.order_by(StorageReservation.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.post("/reservations", response_model=ReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    if payload.status not in STORAGE_RESERVATION_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {payload.status}")
    reservation = StorageReservation(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.patch("/reservations/{reservation_id}", response_model=ReservationResponse)
async def update_reservation(
    reservation_id: uuid.UUID,
    payload: ReservationBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    reservation = await load_or_404(
        db, StorageReservation, reservation_id, current_user.organization_id,
        extra_filters=[StorageReservation.is_deleted.is_(False)],
        detail="Reservation not found",
    )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(reservation, field, value)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.delete("/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reservation(
    reservation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    reservation = await load_or_404(
        db, StorageReservation, reservation_id, current_user.organization_id,
        extra_filters=[StorageReservation.is_deleted.is_(False)],
        detail="Reservation not found",
    )
    reservation.is_deleted = True
    await db.commit()


# ---------------------------------------------------------------------------
# Rate plans
# ---------------------------------------------------------------------------

@router.get("/rate-plans", response_model=list[RatePlanResponse])
async def list_rate_plans(
    facility_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(StorageRatePlan).where(
        StorageRatePlan.organization_id == current_user.organization_id,
        StorageRatePlan.is_deleted.is_(False),
    )
    if facility_id is not None:
        stmt = stmt.where(StorageRatePlan.facility_id == facility_id)
    stmt = stmt.order_by(StorageRatePlan.size_tier)
    return (await db.execute(stmt)).scalars().all()


@router.post("/rate-plans", response_model=RatePlanResponse, status_code=status.HTTP_201_CREATED)
async def create_rate_plan(
    payload: RatePlanBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    plan = StorageRatePlan(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.patch("/rate-plans/{plan_id}", response_model=RatePlanResponse)
async def update_rate_plan(
    plan_id: uuid.UUID,
    payload: RatePlanBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    plan = await load_or_404(
        db, StorageRatePlan, plan_id, current_user.organization_id,
        extra_filters=[StorageRatePlan.is_deleted.is_(False)],
        detail="Rate plan not found",
    )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/rate-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    plan = await load_or_404(
        db, StorageRatePlan, plan_id, current_user.organization_id,
        extra_filters=[StorageRatePlan.is_deleted.is_(False)],
        detail="Rate plan not found",
    )
    plan.is_deleted = True
    await db.commit()


@router.post("/rate-plans/{plan_id}/apply-increase")
async def apply_increase(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    plan = await load_or_404(
        db, StorageRatePlan, plan_id, current_user.organization_id,
        extra_filters=[StorageRatePlan.is_deleted.is_(False)],
        detail="Rate plan not found",
    )
    return await svc.apply_scheduled_increase(db, current_user.organization_id, plan)


# ---------------------------------------------------------------------------
# Charges / billing
# ---------------------------------------------------------------------------

@router.get("/charges", response_model=list[ChargeResponse])
async def list_charges(
    agreement_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Finance),
):
    stmt = select(StorageCharge).where(
        StorageCharge.organization_id == current_user.organization_id,
        StorageCharge.is_deleted.is_(False),
    )
    if agreement_id is not None:
        stmt = stmt.where(StorageCharge.storage_agreement_id == agreement_id)
    stmt = stmt.order_by(StorageCharge.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.post("/charges", response_model=ChargeResponse, status_code=status.HTTP_201_CREATED)
async def create_charge(
    payload: ChargeBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Finance),
):
    org_id = current_user.organization_id
    await load_or_404(
        db, StorageAgreement, payload.storage_agreement_id, org_id,
        extra_filters=[StorageAgreement.is_deleted.is_(False)],
        detail="Storage agreement not found",
    )
    charge = StorageCharge(organization_id=org_id, **payload.model_dump())
    db.add(charge)
    await db.commit()
    await db.refresh(charge)
    return charge


@router.patch("/charges/{charge_id}", response_model=ChargeResponse)
async def update_charge(
    charge_id: uuid.UUID,
    payload: ChargeBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Finance),
):
    charge = await load_or_404(
        db, StorageCharge, charge_id, current_user.organization_id,
        extra_filters=[StorageCharge.is_deleted.is_(False)],
        detail="Storage charge not found",
    )
    for field, value in payload.model_dump(exclude_unset=True, exclude={"storage_agreement_id"}).items():
        setattr(charge, field, value)
    await db.commit()
    await db.refresh(charge)
    return charge


@router.delete("/charges/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_charge(
    charge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Finance),
):
    charge = await load_or_404(
        db, StorageCharge, charge_id, current_user.organization_id,
        extra_filters=[StorageCharge.is_deleted.is_(False)],
        detail="Storage charge not found",
    )
    charge.is_deleted = True
    charge.active = False
    await db.commit()


@router.post("/run-billing")
async def run_billing(
    as_of: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Finance),
):
    try:
        return await svc.run_recurring_billing(
            db, current_user.organization_id, as_of=as_of, posted_by_id=current_user.id
        )
    except SelfStorageError as exc:
        raise _fail(exc)


@router.post("/payments")
async def record_payment(
    payload: PaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Finance),
):
    invoice = await load_or_404(
        db, CustomerInvoice, payload.invoice_id, current_user.organization_id,
        detail="Invoice not found",
    )
    try:
        return await svc.record_storage_payment(
            db, current_user.organization_id, invoice, payload.amount,
            method=payload.method, receipt_date=payload.receipt_date,
            reference=payload.reference, created_by_id=current_user.id,
        )
    except SelfStorageError as exc:
        raise _fail(exc)


# ---------------------------------------------------------------------------
# Occupancy / revenue summary
# ---------------------------------------------------------------------------

@router.get("/occupancy-summary")
async def occupancy_summary(
    facility_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await svc.occupancy_summary(
        db, current_user.organization_id, facility_id=facility_id
    )

"""Leasing (org-as-lessor) API router (Phase 2.1) — ``/api/v1/leasing``.

The tenant/resident domain: leasable rental units, resident (occupant) records,
the org-as-lessor resident leases, and the lease-to-resident occupant links. This
is the *lessor* counterpart to the office ``/api/v1/leases`` router (where the org
is the *lessee*); the two lease directions are separate surfaces.

Reads are open to any authenticated org user; writes require ``admin``/``editor``
and destructive deletes require ``admin`` (mirroring the offices router). Amounts
are USD-only for now.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.office import Office
from app.models.organization import Organization
from app.models.resident import (
    OCCUPANT_ROLES,
    RESIDENT_LEASE_STATUSES,
    RESIDENT_STATUSES,
    LEASE_TYPES,
    UNIT_STATUSES,
    RentalUnit,
    Resident,
    ResidentLease,
    ResidentLeaseOccupant,
)
from app.models.user import User
from app.services import lease_limits
from app.services import leasing_service as svc
from app.services.leasing_service import LeasingError
from app.utils.tenant_scope import load_or_404

router = APIRouter()

# Write access mirrors the offices router: admin/editor manage, admin deletes.
Editor = require_role("admin", "editor")
Admin = require_role("admin")


# ─── Schemas: Rental Unit ─────────────────────────────────────────────────────

class RentalUnitCreate(BaseModel):
    office_id: uuid.UUID | None = None
    unit_number: str
    name: str | None = None
    floor: str | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    square_feet: Decimal | None = None
    market_rent: Decimal | None = None
    currency: str = "USD"
    status: str = "available"
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    property_type: str | None = None
    description: str | None = None
    amenities: str | None = None
    year_built: int | None = None
    available_date: date | None = None
    notes: str | None = None


class RentalUnitUpdate(BaseModel):
    office_id: uuid.UUID | None = None
    unit_number: str | None = None
    name: str | None = None
    floor: str | None = None
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    square_feet: Decimal | None = None
    market_rent: Decimal | None = None
    currency: str | None = None
    status: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    property_type: str | None = None
    description: str | None = None
    amenities: str | None = None
    year_built: int | None = None
    available_date: date | None = None
    notes: str | None = None


class RentalUnitResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    office_id: uuid.UUID | None
    unit_number: str
    name: str | None
    floor: str | None
    bedrooms: int | None
    bathrooms: Decimal | None
    square_feet: Decimal | None
    market_rent: Decimal | None
    currency: str
    status: str
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    property_type: str | None
    description: str | None
    amenities: str | None
    year_built: int | None
    available_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Schemas: Resident ────────────────────────────────────────────────────────

class ResidentCreate(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    date_of_birth: date | None = None
    company: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    status: str = "prospect"
    notes: str | None = None


class ResidentUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    date_of_birth: date | None = None
    company: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    status: str | None = None
    notes: str | None = None


class ResidentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    alternate_phone: str | None
    date_of_birth: date | None
    company: str | None
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Schemas: Occupant link ───────────────────────────────────────────────────

class OccupantInput(BaseModel):
    resident_id: uuid.UUID
    role: str = "primary"
    is_primary: bool = False


class OccupantResponse(BaseModel):
    id: uuid.UUID
    resident_id: uuid.UUID
    role: str
    is_primary: bool
    resident: ResidentResponse | None = None

    model_config = {"from_attributes": True}


# ─── Schemas: Resident Lease ──────────────────────────────────────────────────

class ResidentLeaseCreate(BaseModel):
    unit_id: uuid.UUID
    name: str | None = None
    status: str = "draft"
    start_date: date | None = None
    end_date: date | None = None
    move_in_date: date | None = None
    move_out_date: date | None = None
    rent_amount: Decimal | None = None
    rent_frequency: str = "monthly"
    rent_due_day: int | None = None
    security_deposit: Decimal | None = None
    lease_type: str | None = None
    rent_escalation_rate: Decimal | None = None
    late_fee_amount: Decimal | None = None
    late_fee_grace_days: int | None = None
    notice_period_days: int | None = None
    pet_deposit: Decimal | None = None
    renewal_option: bool = False
    currency: str = "USD"
    notes: str | None = None
    lease_template_id: uuid.UUID | None = None
    template_field_values: dict | None = None
    occupants: list[OccupantInput] = []


class ResidentLeaseUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    move_in_date: date | None = None
    move_out_date: date | None = None
    rent_amount: Decimal | None = None
    rent_frequency: str | None = None
    rent_due_day: int | None = None
    security_deposit: Decimal | None = None
    lease_type: str | None = None
    rent_escalation_rate: Decimal | None = None
    late_fee_amount: Decimal | None = None
    late_fee_grace_days: int | None = None
    notice_period_days: int | None = None
    pet_deposit: Decimal | None = None
    renewal_option: bool | None = None
    currency: str | None = None
    notes: str | None = None
    lease_template_id: uuid.UUID | None = None
    template_field_values: dict | None = None
    occupants: list[OccupantInput] | None = None


class ResidentLeaseResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    unit_id: uuid.UUID
    name: str | None
    status: str
    start_date: date | None
    end_date: date | None
    move_in_date: date | None
    move_out_date: date | None
    rent_amount: Decimal | None
    rent_frequency: str
    rent_due_day: int | None
    security_deposit: Decimal | None
    lease_type: str | None
    rent_escalation_rate: Decimal | None
    late_fee_amount: Decimal | None
    late_fee_grace_days: int | None
    notice_period_days: int | None
    pet_deposit: Decimal | None
    renewal_option: bool
    currency: str
    notes: str | None
    lease_template_id: uuid.UUID | None
    template_field_values: dict | None
    created_at: datetime
    updated_at: datetime
    occupants: list[OccupantResponse]

    model_config = {"from_attributes": True}


class OccupancySummary(BaseModel):
    total_units: int
    counts: dict[str, int]
    occupancy_rate: float


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _validate_choice(value: str | None, allowed: tuple[str, ...], label: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {label} '{value}'. Allowed: {', '.join(allowed)}.",
        )


def _validate_currency(currency: str | None) -> None:
    if currency and currency.upper() != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only USD is supported; multi-currency is not yet available.",
        )


async def _get_unit(db: AsyncSession, unit_id: uuid.UUID, org_id) -> RentalUnit:
    unit = (
        await db.execute(
            select(RentalUnit).where(
                RentalUnit.id == unit_id,
                RentalUnit.organization_id == org_id,
                RentalUnit.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rental unit not found")
    return unit


async def _get_resident(db: AsyncSession, resident_id: uuid.UUID, org_id) -> Resident:
    resident = (
        await db.execute(
            select(Resident).where(
                Resident.id == resident_id,
                Resident.organization_id == org_id,
                Resident.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not resident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    return resident


async def _load_lease(db: AsyncSession, lease_id: uuid.UUID, org_id) -> ResidentLease:
    db.expunge_all()
    lease = await load_or_404(
        db,
        ResidentLease,
        lease_id,
        org_id,
        extra_filters=[ResidentLease.is_deleted.is_(False)],
        detail="Resident lease not found",
    )
    await db.refresh(lease, attribute_names=["occupants"])
    for occupant in lease.occupants:
        await db.refresh(occupant, attribute_names=["resident"])
    return lease


async def _validate_office(db: AsyncSession, office_id: uuid.UUID | None, org_id) -> None:
    if office_id is None:
        return
    exists = (
        await db.execute(
            select(Office.id).where(
                Office.id == office_id,
                Office.organization_id == org_id,
                Office.is_deleted.is_(False),
            )
        )
    ).first()
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown office_id for this organization.",
        )


async def _build_occupants(
    db: AsyncSession,
    occupants: list[OccupantInput],
    org_id,
) -> list[ResidentLeaseOccupant]:
    """Validate occupant inputs and build (unattached) link rows.

    Runs all resident lookups/validation *before* constructing any ORM link
    objects so no partially-built lease is left in the session on error.
    """
    seen: set[uuid.UUID] = set()
    for occ in occupants:
        _validate_choice(occ.role, OCCUPANT_ROLES, "occupant role")
        if occ.resident_id in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A resident may only appear once per lease.",
            )
        seen.add(occ.resident_id)
        # Ensure each referenced resident belongs to the org.
        await _get_resident(db, occ.resident_id, org_id)
    return [
        ResidentLeaseOccupant(
            resident_id=occ.resident_id,
            role=occ.role,
            is_primary=occ.is_primary,
        )
        for occ in occupants
    ]


# ─── Occupancy summary ────────────────────────────────────────────────────────

@router.get("/occupancy", response_model=OccupancySummary)
async def occupancy(
    office_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Portfolio occupancy summary (unit counts by status + occupancy rate)."""
    data = await svc.occupancy_summary(
        db, current_user.organization_id, office_id=office_id
    )
    return OccupancySummary(**data)


# ─── Rental unit endpoints ────────────────────────────────────────────────────

@router.get("/units", response_model=list[RentalUnitResponse])
async def list_units(
    office_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(RentalUnit)
        .where(
            RentalUnit.organization_id == current_user.organization_id,
            RentalUnit.is_deleted.is_(False),
        )
        .order_by(RentalUnit.unit_number)
    )
    if office_id:
        stmt = stmt.where(RentalUnit.office_id == office_id)
    if status_filter:
        stmt = stmt.where(RentalUnit.status == status_filter)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            RentalUnit.unit_number.ilike(like) | RentalUnit.name.ilike(like)
        )
    result = await db.execute(stmt)
    return [RentalUnitResponse.model_validate(u) for u in result.scalars().all()]


@router.post("/units", response_model=RentalUnitResponse, status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: RentalUnitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    _validate_choice(payload.status, UNIT_STATUSES, "status")
    _validate_currency(payload.currency)
    await _validate_office(db, payload.office_id, current_user.organization_id)
    unit = RentalUnit(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(unit)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A unit with this number already exists for the property.",
        )
    await db.refresh(unit)
    return RentalUnitResponse.model_validate(unit)


@router.get("/units/{unit_id}", response_model=RentalUnitResponse)
async def get_unit(
    unit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = await _get_unit(db, unit_id, current_user.organization_id)
    return RentalUnitResponse.model_validate(unit)


@router.patch("/units/{unit_id}", response_model=RentalUnitResponse)
async def update_unit(
    unit_id: uuid.UUID,
    payload: RentalUnitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    unit = await _get_unit(db, unit_id, current_user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_choice(data.get("status"), UNIT_STATUSES, "status")
    _validate_currency(data.get("currency"))
    if "office_id" in data:
        await _validate_office(db, data["office_id"], current_user.organization_id)
    for field, value in data.items():
        setattr(unit, field, value)
    await db.commit()
    await db.refresh(unit)
    return RentalUnitResponse.model_validate(unit)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(
    unit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    unit = await _get_unit(db, unit_id, current_user.organization_id)
    has_active = (
        await db.execute(
            select(ResidentLease.id).where(
                ResidentLease.unit_id == unit.id,
                ResidentLease.is_deleted.is_(False),
                ResidentLease.status.in_(("pending", "active")),
            ).limit(1)
        )
    ).first()
    if has_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a unit with an active or pending lease.",
        )
    unit.is_deleted = True
    unit.deleted_at = datetime.now(timezone.utc)
    await db.commit()


# ─── Resident endpoints ───────────────────────────────────────────────────────

@router.get("/residents", response_model=list[ResidentResponse])
async def list_residents(
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Resident)
        .where(
            Resident.organization_id == current_user.organization_id,
            Resident.is_deleted.is_(False),
        )
        .order_by(Resident.last_name, Resident.first_name)
    )
    if status_filter:
        stmt = stmt.where(Resident.status == status_filter)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Resident.first_name.ilike(like)
            | Resident.last_name.ilike(like)
            | Resident.email.ilike(like)
        )
    result = await db.execute(stmt)
    return [ResidentResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/residents", response_model=ResidentResponse, status_code=status.HTTP_201_CREATED)
async def create_resident(
    payload: ResidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    _validate_choice(payload.status, RESIDENT_STATUSES, "status")
    resident = Resident(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(resident)
    await db.commit()
    await db.refresh(resident)
    return ResidentResponse.model_validate(resident)


@router.get("/residents/{resident_id}", response_model=ResidentResponse)
async def get_resident(
    resident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resident = await _get_resident(db, resident_id, current_user.organization_id)
    return ResidentResponse.model_validate(resident)


@router.patch("/residents/{resident_id}", response_model=ResidentResponse)
async def update_resident(
    resident_id: uuid.UUID,
    payload: ResidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    resident = await _get_resident(db, resident_id, current_user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_choice(data.get("status"), RESIDENT_STATUSES, "status")
    for field, value in data.items():
        setattr(resident, field, value)
    await db.commit()
    await db.refresh(resident)
    return ResidentResponse.model_validate(resident)


@router.delete("/residents/{resident_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resident(
    resident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    resident = await _get_resident(db, resident_id, current_user.organization_id)
    resident.is_deleted = True
    resident.deleted_at = datetime.now(timezone.utc)
    await db.commit()


# ─── Resident lease endpoints ─────────────────────────────────────────────────

@router.get("/leases", response_model=list[ResidentLeaseResponse])
async def list_leases(
    unit_id: uuid.UUID | None = Query(default=None),
    resident_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(ResidentLease)
        .where(
            ResidentLease.organization_id == current_user.organization_id,
            ResidentLease.is_deleted.is_(False),
        )
        .options(
            selectinload(ResidentLease.occupants).selectinload(
                ResidentLeaseOccupant.resident
            )
        )
        .order_by(ResidentLease.created_at.desc())
    )
    if unit_id:
        stmt = stmt.where(ResidentLease.unit_id == unit_id)
    if status_filter:
        stmt = stmt.where(ResidentLease.status == status_filter)
    if resident_id:
        stmt = stmt.where(
            ResidentLease.occupants.any(
                ResidentLeaseOccupant.resident_id == resident_id
            )
        )
    result = await db.execute(stmt)
    return [
        ResidentLeaseResponse.model_validate(l)
        for l in result.scalars().unique().all()
    ]


@router.post("/leases", response_model=ResidentLeaseResponse, status_code=status.HTTP_201_CREATED)
async def create_lease(
    payload: ResidentLeaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    _validate_choice(payload.status, RESIDENT_LEASE_STATUSES, "status")
    _validate_choice(payload.lease_type, LEASE_TYPES, "lease type")
    _validate_currency(payload.currency)
    await _get_unit(db, payload.unit_id, org_id)
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lease end date cannot precede the start date.",
        )
    # Enforce the plan's active-lease cap before creating an active lease.
    if lease_limits.is_active_resident_status(payload.status):
        org = (
            await db.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()
        await lease_limits.enforce_active_lease_limit(db, org)
    if payload.status in ("pending", "active"):
        try:
            await svc.assert_no_active_overlap(
                db,
                payload.unit_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
            )
        except LeasingError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    data = payload.model_dump(exclude={"occupants"})
    occupants = await _build_occupants(db, payload.occupants, org_id)
    lease = ResidentLease(organization_id=org_id, occupants=occupants, **data)
    db.add(lease)
    await db.flush()
    await svc.sync_unit_status(db, lease.unit_id, org_id)
    await db.commit()
    return await _serialize_lease(db, lease.id, org_id)


@router.get("/leases/{lease_id}", response_model=ResidentLeaseResponse)
async def get_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lease = await _load_lease(db, lease_id, current_user.organization_id)
    return ResidentLeaseResponse.model_validate(lease)


@router.patch("/leases/{lease_id}", response_model=ResidentLeaseResponse)
async def update_lease(
    lease_id: uuid.UUID,
    payload: ResidentLeaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    lease = await _load_lease(db, lease_id, org_id)
    data = payload.model_dump(exclude_unset=True, exclude={"occupants"})
    _validate_choice(data.get("status"), RESIDENT_LEASE_STATUSES, "status")
    _validate_choice(data.get("lease_type"), LEASE_TYPES, "lease type")
    _validate_currency(data.get("currency"))

    new_status = data.get("status", lease.status)
    new_start = data.get("start_date", lease.start_date)
    new_end = data.get("end_date", lease.end_date)
    if new_start and new_end and new_end < new_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lease end date cannot precede the start date.",
        )
    if new_status in ("pending", "active"):
        try:
            await svc.assert_no_active_overlap(
                db,
                lease.unit_id,
                start_date=new_start,
                end_date=new_end,
                exclude_lease_id=lease.id,
            )
        except LeasingError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    for field, value in data.items():
        setattr(lease, field, value)
    if payload.occupants is not None:
        # lease.occupants was eagerly loaded by _load_lease, so replacing the
        # collection here will not trigger an implicit async lazy-load.
        lease.occupants = await _build_occupants(db, payload.occupants, org_id)
    await db.flush()
    await svc.sync_unit_status(db, lease.unit_id, org_id)
    await db.commit()
    return await _serialize_lease(db, lease.id, org_id)


@router.delete("/leases/{lease_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    org_id = current_user.organization_id
    lease = await _load_lease(db, lease_id, org_id)
    unit_id = lease.unit_id
    lease.is_deleted = True
    lease.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await svc.sync_unit_status(db, unit_id, org_id)
    await db.commit()


async def _serialize_lease(
    db: AsyncSession, lease_id: uuid.UUID, org_id
) -> ResidentLeaseResponse:
    lease = await _load_lease(db, lease_id, org_id)
    return ResidentLeaseResponse.model_validate(lease)

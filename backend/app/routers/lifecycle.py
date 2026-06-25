"""Lease-lifecycle accounting API router (Phase 4) — `/api/v1/lifecycle`.

Post-commencement ASC 842 / IFRS 16 remeasurement events (modifications,
renewals/option exercises, and partial/full terminations). All endpoints are
gated to the ``admin`` and ``accountant`` roles so finance data stays with
finance staff.

Workflow:
  1. ``POST /events`` computes a draft remeasurement for a lease as of an
     effective date. The pre-event carrying amounts are derived from the lease's
     original schedule unless supplied explicitly.
  2. ``PATCH`` recomputes a draft as terms change; ``DELETE`` removes it.
  3. ``POST /{id}/finalize`` locks the event (immutable, audit-grade).
  4. ``POST /{id}/post-to-gl`` records the remeasurement / gain / loss in the
     general ledger and links the journal entry back to the event.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.lease import Lease
from app.models.lease_lifecycle import LeaseLifecycleEvent
from app.models.user import User
from app.services import lease_lifecycle_service as svc
from app.services.lease_lifecycle_service import LifecycleError

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ────────────────────────────────────────────────────────────────

class LifecycleEventCreate(BaseModel):
    lease_id: uuid.UUID
    event_type: str
    effective_date: date
    # Pre-event carrying amounts; derived from the lease schedule when omitted.
    pre_liability: Decimal | None = None
    pre_rou: Decimal | None = None
    # Revised terms (modification / renewal / remeasured partial termination).
    new_payment_amount: Decimal | None = None
    new_payment_frequency: str | None = None
    new_annual_escalation_rate: Decimal | None = None
    new_incremental_borrowing_rate: Decimal | None = None
    remaining_term_months: int | None = None
    new_expiration: date | None = None
    # Termination parameters.
    remaining_percentage: Decimal | None = None
    termination_penalty: Decimal = Decimal("0")
    notes: str | None = None


class LifecycleEventUpdate(BaseModel):
    effective_date: date | None = None
    pre_liability: Decimal | None = None
    pre_rou: Decimal | None = None
    new_payment_amount: Decimal | None = None
    new_payment_frequency: str | None = None
    new_annual_escalation_rate: Decimal | None = None
    new_incremental_borrowing_rate: Decimal | None = None
    remaining_term_months: int | None = None
    new_expiration: date | None = None
    remaining_percentage: Decimal | None = None
    termination_penalty: Decimal | None = None
    notes: str | None = None


class LifecycleEventResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    lease_id: uuid.UUID
    event_type: str
    effective_date: date
    pre_liability: Decimal
    pre_rou: Decimal
    new_payment_amount: Decimal | None
    new_payment_frequency: str | None
    new_annual_escalation_rate: Decimal | None
    new_incremental_borrowing_rate: Decimal | None
    remaining_term_months: int | None
    new_expiration: date | None
    remaining_percentage: Decimal | None
    termination_penalty: Decimal
    revised_liability: Decimal
    liability_adjustment: Decimal
    rou_adjustment: Decimal
    post_liability: Decimal
    post_rou: Decimal
    gain_loss: Decimal
    status: str
    finalized_at: datetime | None
    journal_entry_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Helpers ────────────────────────────────────────────────────────────────

# Fields carried verbatim from the request onto the event record.
_TERM_FIELDS = (
    "new_payment_amount",
    "new_payment_frequency",
    "new_annual_escalation_rate",
    "new_incremental_borrowing_rate",
    "remaining_term_months",
    "new_expiration",
    "remaining_percentage",
    "termination_penalty",
    "notes",
)


def _compute_inputs(event: LeaseLifecycleEvent) -> dict:
    return {
        "event_type": event.event_type,
        "pre_liability": event.pre_liability,
        "pre_rou": event.pre_rou,
        "new_payment_amount": event.new_payment_amount,
        "new_payment_frequency": event.new_payment_frequency,
        "new_annual_escalation_rate": event.new_annual_escalation_rate,
        "new_incremental_borrowing_rate": event.new_incremental_borrowing_rate,
        "remaining_term_months": event.remaining_term_months,
        "remaining_percentage": event.remaining_percentage,
        "termination_penalty": event.termination_penalty or 0,
    }


async def _get_lease(db: AsyncSession, lease_id: uuid.UUID, org_id) -> Lease:
    lease = (
        await db.execute(
            select(Lease).where(
                Lease.id == lease_id,
                Lease.organization_id == org_id,
                Lease.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")
    return lease


async def _get_event(db: AsyncSession, event_id: uuid.UUID, org_id) -> LeaseLifecycleEvent:
    event = (
        await db.execute(
            select(LeaseLifecycleEvent).where(
                LeaseLifecycleEvent.id == event_id,
                LeaseLifecycleEvent.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/events", response_model=list[LifecycleEventResponse])
async def list_events(
    lease_id: uuid.UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(LeaseLifecycleEvent)
        .where(LeaseLifecycleEvent.organization_id == current_user.organization_id)
        .order_by(
            LeaseLifecycleEvent.effective_date.desc(),
            LeaseLifecycleEvent.created_at.desc(),
        )
    )
    if lease_id:
        stmt = stmt.where(LeaseLifecycleEvent.lease_id == lease_id)
    if event_type:
        stmt = stmt.where(LeaseLifecycleEvent.event_type == event_type)
    result = await db.execute(stmt)
    return [LifecycleEventResponse.model_validate(e) for e in result.scalars().all()]


@router.get("/events/{event_id}", response_model=LifecycleEventResponse)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    event = await _get_event(db, event_id, current_user.organization_id)
    return LifecycleEventResponse.model_validate(event)


@router.post(
    "/events",
    response_model=LifecycleEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_event(
    payload: LifecycleEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Compute and persist a draft lifecycle remeasurement for a lease."""
    lease = await _get_lease(db, payload.lease_id, current_user.organization_id)

    event = LeaseLifecycleEvent(
        organization_id=current_user.organization_id,
        lease_id=payload.lease_id,
        event_type=payload.event_type,
        effective_date=payload.effective_date,
        status="draft",
    )
    for field in _TERM_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(event, field, value)

    # Resolve pre-event carrying amounts: explicit values, else derive them.
    if payload.pre_liability is not None and payload.pre_rou is not None:
        event.pre_liability = payload.pre_liability
        event.pre_rou = payload.pre_rou
    else:
        try:
            pre_liability, pre_rou = svc.derive_pre_event_carrying(
                lease, payload.effective_date
            )
        except LifecycleError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            )
        event.pre_liability = (
            payload.pre_liability if payload.pre_liability is not None else pre_liability
        )
        event.pre_rou = payload.pre_rou if payload.pre_rou is not None else pre_rou

    try:
        result = svc.compute_lifecycle_event(**_compute_inputs(event))
    except LifecycleError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    svc.apply_computation(event, result)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return LifecycleEventResponse.model_validate(event)


@router.patch("/events/{event_id}", response_model=LifecycleEventResponse)
async def update_event(
    event_id: uuid.UUID,
    payload: LifecycleEventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Update a draft event's terms and recompute."""
    event = await _get_event(db, event_id, current_user.organization_id)
    if event.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finalized event cannot be modified.",
        )

    data = payload.model_dump(exclude_unset=True)
    for field in ("effective_date", "pre_liability", "pre_rou", *_TERM_FIELDS):
        if field in data:
            setattr(event, field, data[field])

    try:
        result = svc.compute_lifecycle_event(**_compute_inputs(event))
    except LifecycleError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    svc.apply_computation(event, result)
    await db.commit()
    await db.refresh(event)
    return LifecycleEventResponse.model_validate(event)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    event = await _get_event(db, event_id, current_user.organization_id)
    if event.status == "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finalized event cannot be deleted.",
        )
    await db.delete(event)
    await db.commit()


@router.post("/events/{event_id}/finalize", response_model=LifecycleEventResponse)
async def finalize_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Lock an event so its remeasurement becomes immutable."""
    event = await _get_event(db, event_id, current_user.organization_id)
    if event.status == "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Event is already finalized."
        )
    event.status = "finalized"
    event.finalized_at = datetime.now(timezone.utc)
    event.finalized_by_id = current_user.id
    await db.commit()
    await db.refresh(event)
    return LifecycleEventResponse.model_validate(event)


@router.post("/events/{event_id}/post-to-gl")
async def post_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Post a finalized event's remeasurement / gain / loss into the GL."""
    event = await _get_event(db, event_id, current_user.organization_id)

    try:
        entry = await svc.post_event_to_gl(
            db, current_user.organization_id, event, posted_by_id=current_user.id
        )
    except LifecycleError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return {
        "event_id": event.id,
        "gain_loss": event.gain_loss,
        "journal_entry_id": entry.id if entry else None,
        "posted": entry is not None,
    }

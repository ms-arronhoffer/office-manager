"""Space history — occupancy snapshots per office."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.office import Office
from app.models.space_history import SpaceHistory

router = APIRouter()


class SpaceSnapshotCreate(BaseModel):
    snapshot_date: Optional[datetime] = None
    total_sqft: Optional[float] = None
    usable_sqft: Optional[float] = None
    headcount_capacity: Optional[int] = None
    current_headcount: Optional[int] = None
    space_type: Optional[str] = None
    notes: Optional[str] = None


class SpaceSnapshotResponse(BaseModel):
    id: uuid.UUID
    office_id: uuid.UUID
    snapshot_date: datetime
    total_sqft: Optional[float]
    usable_sqft: Optional[float]
    headcount_capacity: Optional[int]
    current_headcount: Optional[int]
    occupancy_pct: Optional[float]
    sqft_per_person: Optional[float]
    space_type: Optional[str]
    notes: Optional[str]
    recorded_by_id: Optional[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


def _enrich(snap: SpaceHistory) -> SpaceSnapshotResponse:
    usable = float(snap.usable_sqft) if snap.usable_sqft else None
    cap = snap.headcount_capacity
    cur = snap.current_headcount
    occ = round(cur / cap * 100, 1) if (cap and cur is not None) else None
    spp = round(usable / cur, 1) if (usable and cur) else None
    return SpaceSnapshotResponse(
        id=snap.id,
        office_id=snap.office_id,
        snapshot_date=snap.snapshot_date,
        total_sqft=float(snap.total_sqft) if snap.total_sqft else None,
        usable_sqft=usable,
        headcount_capacity=cap,
        current_headcount=cur,
        occupancy_pct=occ,
        sqft_per_person=spp,
        space_type=snap.space_type,
        notes=snap.notes,
        recorded_by_id=snap.recorded_by_id,
        created_at=snap.created_at,
    )


async def _get_office(office_id: uuid.UUID, org_id, db: AsyncSession) -> Office:
    result = await db.execute(
        select(Office).where(Office.id == office_id, Office.organization_id == org_id)
    )
    office = result.scalar_one_or_none()
    if not office:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")
    return office


@router.get("/offices/{office_id}/space-history", response_model=list[SpaceSnapshotResponse])
async def list_space_history(
    office_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_office(office_id, current_user.organization_id, db)
    result = await db.execute(
        select(SpaceHistory)
        .where(SpaceHistory.office_id == office_id)
        .order_by(SpaceHistory.snapshot_date.asc())
    )
    return [_enrich(s) for s in result.scalars().all()]


@router.post(
    "/offices/{office_id}/space-history",
    response_model=SpaceSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_space_snapshot(
    office_id: uuid.UUID,
    payload: SpaceSnapshotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    office = await _get_office(office_id, current_user.organization_id, db)

    snap = SpaceHistory(
        office_id=office_id,
        organization_id=current_user.organization_id,
        snapshot_date=payload.snapshot_date or datetime.now(timezone.utc),
        total_sqft=payload.total_sqft if payload.total_sqft is not None else (float(office.total_sqft) if office.total_sqft else None),
        usable_sqft=payload.usable_sqft if payload.usable_sqft is not None else (float(office.usable_sqft) if office.usable_sqft else None),
        headcount_capacity=payload.headcount_capacity if payload.headcount_capacity is not None else office.headcount_capacity,
        current_headcount=payload.current_headcount if payload.current_headcount is not None else office.current_headcount,
        space_type=payload.space_type or office.space_type,
        notes=payload.notes,
        recorded_by_id=current_user.id,
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return _enrich(snap)


@router.delete(
    "/offices/{office_id}/space-history/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_space_snapshot(
    office_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    result = await db.execute(
        select(SpaceHistory).where(
            SpaceHistory.id == snapshot_id,
            SpaceHistory.office_id == office_id,
        )
    )
    snap = result.scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    await db.delete(snap)
    await db.commit()

"""Work order cost lines — labor and materials tracking."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.maintenance_ticket import MaintenanceTicket, WorkOrderCostLine

router = APIRouter()


class CostLineCreate(BaseModel):
    line_type: str  # "labor" | "material"
    description: str
    quantity: Decimal = Decimal("1")
    unit_cost: Decimal = Decimal("0")


class CostLineUpdate(BaseModel):
    line_type: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_cost: Optional[Decimal] = None


class CostLineResponse(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    line_type: str
    description: str
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal = Decimal("0")

    class Config:
        from_attributes = True


class WorkOrderCostSummary(BaseModel):
    labor_total: Decimal
    materials_total: Decimal
    grand_total: Decimal
    lines: list[CostLineResponse]


def _line_to_response(line: WorkOrderCostLine) -> CostLineResponse:
    r = CostLineResponse.model_validate(line)
    r.total_cost = line.quantity * line.unit_cost
    return r


async def _get_ticket(ticket_id: uuid.UUID, org_id: uuid.UUID | None, db: AsyncSession) -> MaintenanceTicket:
    result = await db.execute(
        select(MaintenanceTicket).where(
            MaintenanceTicket.id == ticket_id,
            MaintenanceTicket.organization_id == org_id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


@router.get("/maintenance-tickets/{ticket_id}/cost-lines", response_model=WorkOrderCostSummary)
async def list_cost_lines(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_ticket(ticket_id, current_user.organization_id, db)
    result = await db.execute(
        select(WorkOrderCostLine)
        .where(WorkOrderCostLine.ticket_id == ticket_id)
        .order_by(WorkOrderCostLine.created_at)
    )
    lines = result.scalars().all()
    line_responses = [_line_to_response(ln) for ln in lines]
    labor_total = sum(
        (ln.quantity * ln.unit_cost for ln in lines if ln.line_type == "labor"), Decimal("0")
    )
    materials_total = sum(
        (ln.quantity * ln.unit_cost for ln in lines if ln.line_type == "material"), Decimal("0")
    )
    return WorkOrderCostSummary(
        labor_total=labor_total,
        materials_total=materials_total,
        grand_total=labor_total + materials_total,
        lines=line_responses,
    )


@router.post(
    "/maintenance-tickets/{ticket_id}/cost-lines",
    response_model=CostLineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cost_line(
    ticket_id: uuid.UUID,
    payload: CostLineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    await _get_ticket(ticket_id, current_user.organization_id, db)

    if payload.line_type not in ("labor", "material"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="line_type must be 'labor' or 'material'")

    line = WorkOrderCostLine(ticket_id=ticket_id, **payload.model_dump())
    db.add(line)
    await db.commit()
    await db.refresh(line)
    return _line_to_response(line)


@router.patch("/maintenance-tickets/{ticket_id}/cost-lines/{line_id}", response_model=CostLineResponse)
async def update_cost_line(
    ticket_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: CostLineUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    await _get_ticket(ticket_id, current_user.organization_id, db)

    result = await db.execute(
        select(WorkOrderCostLine).where(
            WorkOrderCostLine.id == line_id,
            WorkOrderCostLine.ticket_id == ticket_id,
        )
    )
    line = result.scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(line, field, value)
    await db.commit()
    await db.refresh(line)
    return _line_to_response(line)


@router.delete(
    "/maintenance-tickets/{ticket_id}/cost-lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cost_line(
    ticket_id: uuid.UUID,
    line_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    await _get_ticket(ticket_id, current_user.organization_id, db)

    result = await db.execute(
        select(WorkOrderCostLine).where(
            WorkOrderCostLine.id == line_id,
            WorkOrderCostLine.ticket_id == ticket_id,
        )
    )
    line = result.scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
    await db.delete(line)
    await db.commit()


# ── Work Order Scheduling ────────────────────────────────────────────────────

class WorkOrderScheduleUpdate(BaseModel):
    scheduled_date: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    actual_start_at: Optional[datetime] = None
    actual_end_at: Optional[datetime] = None
    technician_name: Optional[str] = None


class WorkOrderScheduleResponse(BaseModel):
    ticket_id: uuid.UUID
    scheduled_date: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    actual_start_at: Optional[datetime] = None
    actual_end_at: Optional[datetime] = None
    technician_name: Optional[str] = None

    class Config:
        from_attributes = True


@router.patch(
    "/maintenance-tickets/{ticket_id}/schedule",
    response_model=WorkOrderScheduleResponse,
)
async def update_work_order_schedule(
    ticket_id: uuid.UUID,
    payload: WorkOrderScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update scheduling fields for a work order (admin/editor only)."""
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    ticket = await _get_ticket(ticket_id, current_user.organization_id, db)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(ticket, field, value)
    await db.commit()
    await db.refresh(ticket)

    return WorkOrderScheduleResponse(
        ticket_id=ticket.id,
        scheduled_date=ticket.scheduled_date,
        estimated_duration_minutes=ticket.estimated_duration_minutes,
        actual_start_at=ticket.actual_start_at,
        actual_end_at=ticket.actual_end_at,
        technician_name=ticket.technician_name,
    )


# ── QR Code ──────────────────────────────────────────────────────────────────

@router.get("/maintenance-tickets/{ticket_id}/qr")
async def get_ticket_qr(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the URL to encode in a QR code for this ticket."""
    await _get_ticket(ticket_id, current_user.organization_id, db)
    from app.config import settings
    ticket_url = f"{settings.FRONTEND_URL.rstrip('/')}/maintenance/{ticket_id}"
    return JSONResponse({"ticket_id": str(ticket_id), "url": ticket_url})

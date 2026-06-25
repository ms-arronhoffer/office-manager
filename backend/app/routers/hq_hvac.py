import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.hq_hvac import (
    HqBackflow,
    HqHeatPump,
    HqHeatPumpServiceLog,
    HqHvacIssue,
    HqMaintenanceContract,
    HqPmLog,
    HqPmTask,
)
from app.models.user import User
from app.schemas.hq_hvac import (
    BackflowCreate,
    BackflowResponse,
    BackflowUpdate,
    HeatPumpCreate,
    HeatPumpResponse,
    HeatPumpServiceLogCreate,
    HeatPumpServiceLogResponse,
    HeatPumpUpdate,
    HvacIssueCreate,
    HvacIssueResponse,
    HvacIssueUpdate,
    MaintenanceContractCreate,
    MaintenanceContractResponse,
    MaintenanceContractUpdate,
    PmLogCreate,
    PmLogResponse,
    PmLogUpdate,
    PmTaskCreate,
    PmTaskResponse,
    PmTaskUpdate,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Heat Pumps
# ---------------------------------------------------------------------------

@router.get("/heat-pumps", response_model=list[HeatPumpResponse])
async def list_heat_pumps(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HqHeatPump).options(joinedload(HqHeatPump.service_logs)).order_by(HqHeatPump.unit_id)
    )
    return [HeatPumpResponse.model_validate(p, from_attributes=True) for p in result.scalars().unique().all()]


@router.post("/heat-pumps", response_model=HeatPumpResponse, status_code=status.HTTP_201_CREATED)
async def create_heat_pump(
    payload: HeatPumpCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    pump = HqHeatPump(**payload.model_dump())
    db.add(pump)
    await db.commit()
    await db.refresh(pump)
    result = await db.execute(
        select(HqHeatPump).options(joinedload(HqHeatPump.service_logs)).where(HqHeatPump.id == pump.id)
    )
    return HeatPumpResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.get("/heat-pumps/{pump_id}", response_model=HeatPumpResponse)
async def get_heat_pump(
    pump_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HqHeatPump)
        .options(joinedload(HqHeatPump.service_logs))
        .where(HqHeatPump.id == pump_id)
    )
    pump = result.unique().scalar_one_or_none()
    if not pump:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Heat pump not found")
    return HeatPumpResponse.model_validate(pump, from_attributes=True)


@router.put("/heat-pumps/{pump_id}", response_model=HeatPumpResponse)
async def update_heat_pump(
    pump_id: uuid.UUID,
    payload: HeatPumpUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqHeatPump).where(HqHeatPump.id == pump_id))
    pump = result.scalar_one_or_none()
    if not pump:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Heat pump not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(pump, field, value)

    await db.commit()

    result = await db.execute(
        select(HqHeatPump)
        .options(joinedload(HqHeatPump.service_logs))
        .where(HqHeatPump.id == pump_id)
    )
    return HeatPumpResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.post(
    "/heat-pumps/{pump_id}/service-log",
    response_model=HeatPumpServiceLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_service_log(
    pump_id: uuid.UUID,
    payload: HeatPumpServiceLogCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqHeatPump).where(HqHeatPump.id == pump_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Heat pump not found")

    log = HqHeatPumpServiceLog(heat_pump_id=pump_id, **payload.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return HeatPumpServiceLogResponse.model_validate(log, from_attributes=True)


@router.delete("/heat-pumps/{pump_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_heat_pump(
    pump_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqHeatPump).where(HqHeatPump.id == pump_id))
    pump = result.scalar_one_or_none()
    if not pump:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Heat pump not found")
    await db.delete(pump)
    await db.commit()


# ---------------------------------------------------------------------------
# HVAC Issues
# ---------------------------------------------------------------------------

@router.get("/issues", response_model=list[HvacIssueResponse])
async def list_issues(
    issue_status: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(HqHvacIssue)
    if issue_status:
        stmt = stmt.where(HqHvacIssue.status == issue_status)
    stmt = stmt.order_by(HqHvacIssue.issue_date.desc())
    result = await db.execute(stmt)
    return [HvacIssueResponse.model_validate(i, from_attributes=True) for i in result.scalars().all()]


@router.post("/issues", response_model=HvacIssueResponse, status_code=status.HTTP_201_CREATED)
async def create_issue(
    payload: HvacIssueCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    issue = HqHvacIssue(**payload.model_dump())
    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    return HvacIssueResponse.model_validate(issue, from_attributes=True)


@router.put("/issues/{issue_id}", response_model=HvacIssueResponse)
async def update_issue(
    issue_id: uuid.UUID,
    payload: HvacIssueUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqHvacIssue).where(HqHvacIssue.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(issue, field, value)

    await db.commit()
    await db.refresh(issue)
    return HvacIssueResponse.model_validate(issue, from_attributes=True)


@router.delete("/issues/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_issue(
    issue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqHvacIssue).where(HqHvacIssue.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    await db.delete(issue)
    await db.commit()


# ---------------------------------------------------------------------------
# PM Tasks
# ---------------------------------------------------------------------------

@router.get("/pm-tasks", response_model=list[PmTaskResponse])
async def list_pm_tasks(
    category: str | None = Query(default=None),
    task_status: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(HqPmTask)
    if category:
        stmt = stmt.where(HqPmTask.equipment_category == category)
    if task_status:
        stmt = stmt.where(HqPmTask.status == task_status)
    stmt = stmt.order_by(HqPmTask.next_due_date)
    result = await db.execute(stmt)
    return [PmTaskResponse.model_validate(t, from_attributes=True) for t in result.scalars().all()]


@router.post("/pm-tasks", response_model=PmTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_pm_task(
    payload: PmTaskCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    task = HqPmTask(**payload.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return PmTaskResponse.model_validate(task, from_attributes=True)


@router.put("/pm-tasks/{task_id}", response_model=PmTaskResponse)
async def update_pm_task(
    task_id: uuid.UUID,
    payload: PmTaskUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqPmTask).where(HqPmTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PM task not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)
    return PmTaskResponse.model_validate(task, from_attributes=True)


@router.delete("/pm-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pm_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqPmTask).where(HqPmTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PM task not found")
    await db.delete(task)
    await db.commit()


# ---------------------------------------------------------------------------
# PM Log
# ---------------------------------------------------------------------------

@router.get("/pm-log", response_model=list[PmLogResponse])
async def list_pm_log(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqPmLog).order_by(HqPmLog.date_of_visit.desc()))
    return [PmLogResponse.model_validate(l, from_attributes=True) for l in result.scalars().all()]


@router.post("/pm-log", response_model=PmLogResponse, status_code=status.HTTP_201_CREATED)
async def create_pm_log(
    payload: PmLogCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from datetime import datetime, timezone
    log = HqPmLog(timestamp=datetime.now(timezone.utc), **payload.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return PmLogResponse.model_validate(log, from_attributes=True)


@router.put("/pm-log/{log_id}", response_model=PmLogResponse)
async def update_pm_log(
    log_id: uuid.UUID,
    payload: PmLogUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqPmLog).where(HqPmLog.id == log_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PM log entry not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log, field, value)

    await db.commit()
    await db.refresh(log)
    return PmLogResponse.model_validate(log, from_attributes=True)


@router.delete("/pm-log/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pm_log(
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqPmLog).where(HqPmLog.id == log_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PM log entry not found")
    await db.delete(log)
    await db.commit()


# ---------------------------------------------------------------------------
# Maintenance Contracts
# ---------------------------------------------------------------------------

@router.get("/maintenance-contracts", response_model=list[MaintenanceContractResponse])
async def list_maintenance_contracts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HqMaintenanceContract).order_by(HqMaintenanceContract.contractor_name)
    )
    return [MaintenanceContractResponse.model_validate(c, from_attributes=True) for c in result.scalars().all()]


@router.post("/maintenance-contracts", response_model=MaintenanceContractResponse, status_code=status.HTTP_201_CREATED)
async def create_maintenance_contract(
    payload: MaintenanceContractCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    contract = HqMaintenanceContract(**payload.model_dump())
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return MaintenanceContractResponse.model_validate(contract, from_attributes=True)


@router.put("/maintenance-contracts/{contract_id}", response_model=MaintenanceContractResponse)
async def update_maintenance_contract(
    contract_id: uuid.UUID,
    payload: MaintenanceContractUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqMaintenanceContract).where(HqMaintenanceContract.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance contract not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contract, field, value)

    await db.commit()
    await db.refresh(contract)
    return MaintenanceContractResponse.model_validate(contract, from_attributes=True)


@router.delete("/maintenance-contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_maintenance_contract(
    contract_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqMaintenanceContract).where(HqMaintenanceContract.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance contract not found")
    await db.delete(contract)
    await db.commit()


# ---------------------------------------------------------------------------
# Backflows
# ---------------------------------------------------------------------------

@router.get("/backflows", response_model=list[BackflowResponse])
async def list_backflows(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqBackflow).order_by(HqBackflow.location_desc))
    return [BackflowResponse.model_validate(b, from_attributes=True) for b in result.scalars().all()]


@router.post("/backflows", response_model=BackflowResponse, status_code=status.HTTP_201_CREATED)
async def create_backflow(
    payload: BackflowCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    backflow = HqBackflow(**payload.model_dump())
    db.add(backflow)
    await db.commit()
    await db.refresh(backflow)
    return BackflowResponse.model_validate(backflow, from_attributes=True)


@router.put("/backflows/{backflow_id}", response_model=BackflowResponse)
async def update_backflow(
    backflow_id: uuid.UUID,
    payload: BackflowUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqBackflow).where(HqBackflow.id == backflow_id))
    backflow = result.scalar_one_or_none()
    if not backflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backflow not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(backflow, field, value)

    await db.commit()
    await db.refresh(backflow)
    return BackflowResponse.model_validate(backflow, from_attributes=True)


@router.delete("/backflows/{backflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backflow(
    backflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(HqBackflow).where(HqBackflow.id == backflow_id))
    backflow = result.scalar_one_or_none()
    if not backflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backflow not found")
    await db.delete(backflow)
    await db.commit()

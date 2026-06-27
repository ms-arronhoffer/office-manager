"""Maintenance program — CRUD for assets, tasks and service logs.

Covers the six property-maintenance domains (HVAC, fire & life safety, plumbing
& backflow, refuse & waste, exterior & structural, elevators & lifts). Tasks
carry a due date, an optionally assigned vendor, and reminder settings; logging a
service visit advances the task's ``last_completed_date`` / ``next_due_date``.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.maintenance import (
    MaintenanceAsset,
    MaintenanceLog,
    MaintenanceTask,
    MAINTENANCE_CATEGORIES,
    MAINTENANCE_CATEGORY_KEYS,
    MAINTENANCE_FREQUENCIES,
    MAINTENANCE_ASSET_STATUSES,
    MAINTENANCE_TASK_STATUSES,
    is_valid_subtopic,
)
from app.models.user import User

router = APIRouter()

# Cadence (in days) used to advance a task's next due date after a service log.
_FREQUENCY_DAYS: dict[str, int] = {
    "monthly": 30,
    "quarterly": 91,
    "semi_annual": 182,
    "annual": 365,
    "seasonal": 91,
}


# ── Summaries ─────────────────────────────────────────────────────────────────

class VendorSummary(BaseModel):
    id: uuid.UUID
    company_name: str

    class Config:
        from_attributes = True


class OfficeSummary(BaseModel):
    id: uuid.UUID
    location_name: str

    class Config:
        from_attributes = True


# ── Asset schemas ─────────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    category: str
    subtopic: Optional[str] = None
    office_id: Optional[uuid.UUID] = None
    name: str
    location_desc: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    install_date: Optional[date] = None
    vendor_id: Optional[uuid.UUID] = None
    is_regulatory: bool = False
    certification_expiry: Optional[date] = None
    status: str = "active"
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    category: Optional[str] = None
    subtopic: Optional[str] = None
    office_id: Optional[uuid.UUID] = None
    name: Optional[str] = None
    location_desc: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    install_date: Optional[date] = None
    vendor_id: Optional[uuid.UUID] = None
    is_regulatory: Optional[bool] = None
    certification_expiry: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AssetResponse(BaseModel):
    id: uuid.UUID
    organization_id: Optional[uuid.UUID] = None
    category: str
    subtopic: Optional[str] = None
    office_id: Optional[uuid.UUID] = None
    name: str
    location_desc: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    install_date: Optional[date] = None
    vendor_id: Optional[uuid.UUID] = None
    is_regulatory: bool
    certification_expiry: Optional[date] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    vendor: Optional[VendorSummary] = None
    office: Optional[OfficeSummary] = None

    class Config:
        from_attributes = True


# ── Task schemas ──────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    category: str
    subtopic: Optional[str] = None
    asset_id: Optional[uuid.UUID] = None
    office_id: Optional[uuid.UUID] = None
    title: str
    description: Optional[str] = None
    frequency: Optional[str] = None
    last_completed_date: Optional[date] = None
    next_due_date: Optional[date] = None
    vendor_id: Optional[uuid.UUID] = None
    status: str = "scheduled"
    is_regulatory: bool = False
    reminder_enabled: bool = False
    reminder_days_before: int = Field(default=14, ge=0, le=365)
    reminder_recipients: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class TaskUpdate(BaseModel):
    category: Optional[str] = None
    subtopic: Optional[str] = None
    asset_id: Optional[uuid.UUID] = None
    office_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None
    frequency: Optional[str] = None
    last_completed_date: Optional[date] = None
    next_due_date: Optional[date] = None
    vendor_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    is_regulatory: Optional[bool] = None
    reminder_enabled: Optional[bool] = None
    reminder_days_before: Optional[int] = Field(default=None, ge=0, le=365)
    reminder_recipients: Optional[list[str]] = None
    notes: Optional[str] = None


class TaskResponse(BaseModel):
    id: uuid.UUID
    organization_id: Optional[uuid.UUID] = None
    asset_id: Optional[uuid.UUID] = None
    category: str
    subtopic: Optional[str] = None
    office_id: Optional[uuid.UUID] = None
    title: str
    description: Optional[str] = None
    frequency: Optional[str] = None
    last_completed_date: Optional[date] = None
    next_due_date: Optional[date] = None
    vendor_id: Optional[uuid.UUID] = None
    status: str
    is_regulatory: bool
    reminder_enabled: bool
    reminder_days_before: int
    reminder_recipients: list[str]
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    vendor: Optional[VendorSummary] = None
    office: Optional[OfficeSummary] = None
    computed_status: str = ""

    class Config:
        from_attributes = True


# ── Log schemas ───────────────────────────────────────────────────────────────

class LogCreate(BaseModel):
    task_id: Optional[uuid.UUID] = None
    asset_id: Optional[uuid.UUID] = None
    service_date: Optional[date] = None
    performed_by: Optional[str] = None
    vendor_id: Optional[uuid.UUID] = None
    cost: Optional[Decimal] = None
    invoice_number: Optional[str] = None
    description: str
    status: Optional[str] = None


class LogResponse(BaseModel):
    id: uuid.UUID
    task_id: Optional[uuid.UUID] = None
    asset_id: Optional[uuid.UUID] = None
    service_date: Optional[date] = None
    performed_by: Optional[str] = None
    vendor_id: Optional[uuid.UUID] = None
    cost: Optional[Decimal] = None
    invoice_number: Optional[str] = None
    description: str
    status: Optional[str] = None
    created_at: datetime
    vendor: Optional[VendorSummary] = None

    class Config:
        from_attributes = True


class CategorySubtopic(BaseModel):
    value: str
    label: str


class CategoryInfo(BaseModel):
    value: str
    label: str
    subtopics: list[CategorySubtopic]


class CatalogResponse(BaseModel):
    categories: list[CategoryInfo]
    frequencies: list[str]
    task_statuses: list[str]
    asset_statuses: list[str]


class OverviewCategoryStat(BaseModel):
    category: str
    label: str
    task_count: int
    asset_count: int
    overdue: int
    due_soon: int


class OverviewResponse(BaseModel):
    total_tasks: int
    total_assets: int
    overdue: int
    due_soon: int
    expiring_certifications: int
    by_category: list[OverviewCategoryStat]


# ── Helpers ───────────────────────────────────────────────────────────────────

_ASSET_OPTS = (
    selectinload(MaintenanceAsset.vendor),
    selectinload(MaintenanceAsset.office),
)
_TASK_OPTS = (
    selectinload(MaintenanceTask.vendor),
    selectinload(MaintenanceTask.office),
)
_LOG_OPTS = (selectinload(MaintenanceLog.vendor),)


def _require_editor(user: User) -> None:
    if user.role not in ("admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )


def _validate_category(category: str, subtopic: Optional[str]) -> None:
    if category not in MAINTENANCE_CATEGORY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown maintenance category: {category}",
        )
    if not is_valid_subtopic(category, subtopic):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Subtopic '{subtopic}' is not valid for category '{category}'",
        )


def _compute_task_status(task: MaintenanceTask, today: Optional[date] = None) -> str:
    today = today or date.today()
    if task.status == "completed":
        return "completed"
    if task.next_due_date is None:
        return task.status
    if task.next_due_date < today:
        return "overdue"
    if (task.next_due_date - today).days <= 14:
        return "due_soon"
    return task.status


def _task_response(task: MaintenanceTask) -> TaskResponse:
    data = TaskResponse.model_validate(task)
    data.computed_status = _compute_task_status(task)
    return data


# ── Catalog & overview ────────────────────────────────────────────────────────

@router.get("/catalog", response_model=CatalogResponse)
async def get_catalog(current_user: User = Depends(get_current_user)):
    categories = [
        CategoryInfo(
            value=key,
            label=cat["label"],
            subtopics=[
                CategorySubtopic(value=sk, label=sl)
                for sk, sl in cat["subtopics"].items()
            ],
        )
        for key, cat in MAINTENANCE_CATEGORIES.items()
    ]
    return CatalogResponse(
        categories=categories,
        frequencies=list(MAINTENANCE_FREQUENCIES),
        task_statuses=list(MAINTENANCE_TASK_STATUSES),
        asset_statuses=list(MAINTENANCE_ASSET_STATUSES),
    )


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = current_user.organization_id
    tasks = (
        await db.execute(
            select(MaintenanceTask).where(MaintenanceTask.organization_id == org_id)
        )
    ).scalars().all()
    assets = (
        await db.execute(
            select(MaintenanceAsset).where(MaintenanceAsset.organization_id == org_id)
        )
    ).scalars().all()

    today = date.today()
    soon = today + timedelta(days=14)

    by_category: list[OverviewCategoryStat] = []
    overdue_total = due_soon_total = 0
    for key, cat in MAINTENANCE_CATEGORIES.items():
        cat_tasks = [t for t in tasks if t.category == key]
        cat_assets = [a for a in assets if a.category == key]
        cat_overdue = sum(
            1 for t in cat_tasks
            if t.status != "completed" and t.next_due_date and t.next_due_date < today
        )
        cat_due_soon = sum(
            1 for t in cat_tasks
            if t.status != "completed" and t.next_due_date and today <= t.next_due_date <= soon
        )
        overdue_total += cat_overdue
        due_soon_total += cat_due_soon
        by_category.append(
            OverviewCategoryStat(
                category=key,
                label=cat["label"],
                task_count=len(cat_tasks),
                asset_count=len(cat_assets),
                overdue=cat_overdue,
                due_soon=cat_due_soon,
            )
        )

    expiring = sum(
        1 for a in assets
        if a.certification_expiry and today <= a.certification_expiry <= soon
    )

    return OverviewResponse(
        total_tasks=len(tasks),
        total_assets=len(assets),
        overdue=overdue_total,
        due_soon=due_soon_total,
        expiring_certifications=expiring,
        by_category=by_category,
    )


# ── Assets ────────────────────────────────────────────────────────────────────

@router.get("/assets", response_model=list[AssetResponse])
async def list_assets(
    category: Optional[str] = Query(None),
    office_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(MaintenanceAsset)
        .options(*_ASSET_OPTS)
        .where(MaintenanceAsset.organization_id == current_user.organization_id)
    )
    if category:
        q = q.where(MaintenanceAsset.category == category)
    if office_id:
        q = q.where(MaintenanceAsset.office_id == office_id)
    q = q.order_by(MaintenanceAsset.name.asc())
    result = await db.execute(q)
    return [AssetResponse.model_validate(a) for a in result.scalars().all()]


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    _validate_category(payload.category, payload.subtopic)
    asset = MaintenanceAsset(
        organization_id=current_user.organization_id, **payload.model_dump()
    )
    db.add(asset)
    await db.commit()
    result = await db.execute(
        select(MaintenanceAsset).options(*_ASSET_OPTS).where(MaintenanceAsset.id == asset.id)
    )
    return AssetResponse.model_validate(result.scalar_one())


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: uuid.UUID,
    payload: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    result = await db.execute(
        select(MaintenanceAsset)
        .options(*_ASSET_OPTS)
        .where(
            MaintenanceAsset.id == asset_id,
            MaintenanceAsset.organization_id == current_user.organization_id,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    updates = payload.model_dump(exclude_unset=True)
    new_category = updates.get("category", asset.category)
    new_subtopic = updates.get("subtopic", asset.subtopic)
    if "category" in updates or "subtopic" in updates:
        _validate_category(new_category, new_subtopic)
    for field, value in updates.items():
        setattr(asset, field, value)

    await db.commit()
    result = await db.execute(
        select(MaintenanceAsset).options(*_ASSET_OPTS).where(MaintenanceAsset.id == asset.id)
    )
    return AssetResponse.model_validate(result.scalar_one())


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    result = await db.execute(
        select(MaintenanceAsset).where(
            MaintenanceAsset.id == asset_id,
            MaintenanceAsset.organization_id == current_user.organization_id,
        )
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    await db.delete(asset)
    await db.commit()


# ── Tasks ─────────────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    category: Optional[str] = Query(None),
    office_id: Optional[uuid.UUID] = Query(None),
    vendor_id: Optional[uuid.UUID] = Query(None),
    asset_id: Optional[uuid.UUID] = Query(None),
    due_within_days: Optional[int] = Query(None),
    overdue_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(MaintenanceTask)
        .options(*_TASK_OPTS)
        .where(MaintenanceTask.organization_id == current_user.organization_id)
    )
    if category:
        q = q.where(MaintenanceTask.category == category)
    if office_id:
        q = q.where(MaintenanceTask.office_id == office_id)
    if vendor_id:
        q = q.where(MaintenanceTask.vendor_id == vendor_id)
    if asset_id:
        q = q.where(MaintenanceTask.asset_id == asset_id)
    if overdue_only:
        q = q.where(
            MaintenanceTask.next_due_date.is_not(None),
            MaintenanceTask.next_due_date < date.today(),
            MaintenanceTask.status != "completed",
        )
    if due_within_days is not None:
        cutoff = date.today() + timedelta(days=due_within_days)
        q = q.where(
            MaintenanceTask.next_due_date.is_not(None),
            MaintenanceTask.next_due_date >= date.today(),
            MaintenanceTask.next_due_date <= cutoff,
        )
    q = q.order_by(MaintenanceTask.next_due_date.asc().nulls_last())
    result = await db.execute(q)
    return [_task_response(t) for t in result.scalars().all()]


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    _validate_category(payload.category, payload.subtopic)
    task = MaintenanceTask(
        organization_id=current_user.organization_id, **payload.model_dump()
    )
    db.add(task)
    await db.commit()
    result = await db.execute(
        select(MaintenanceTask).options(*_TASK_OPTS).where(MaintenanceTask.id == task.id)
    )
    return _task_response(result.scalar_one())


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    result = await db.execute(
        select(MaintenanceTask)
        .options(*_TASK_OPTS)
        .where(
            MaintenanceTask.id == task_id,
            MaintenanceTask.organization_id == current_user.organization_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    updates = payload.model_dump(exclude_unset=True)
    new_category = updates.get("category", task.category)
    new_subtopic = updates.get("subtopic", task.subtopic)
    if "category" in updates or "subtopic" in updates:
        _validate_category(new_category, new_subtopic)
    for field, value in updates.items():
        setattr(task, field, value)

    await db.commit()
    result = await db.execute(
        select(MaintenanceTask).options(*_TASK_OPTS).where(MaintenanceTask.id == task.id)
    )
    return _task_response(result.scalar_one())


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    result = await db.execute(
        select(MaintenanceTask).where(
            MaintenanceTask.id == task_id,
            MaintenanceTask.organization_id == current_user.organization_id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await db.delete(task)
    await db.commit()


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs", response_model=list[LogResponse])
async def list_logs(
    task_id: Optional[uuid.UUID] = Query(None),
    asset_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(MaintenanceLog)
        .options(*_LOG_OPTS)
        .where(MaintenanceLog.organization_id == current_user.organization_id)
    )
    if task_id:
        q = q.where(MaintenanceLog.task_id == task_id)
    if asset_id:
        q = q.where(MaintenanceLog.asset_id == asset_id)
    q = q.order_by(MaintenanceLog.service_date.desc().nulls_last())
    result = await db.execute(q)
    return [LogResponse.model_validate(log) for log in result.scalars().all()]


@router.post("/logs", response_model=LogResponse, status_code=status.HTTP_201_CREATED)
async def create_log(
    payload: LogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    org_id = current_user.organization_id

    task: Optional[MaintenanceTask] = None
    if payload.task_id:
        task = (
            await db.execute(
                select(MaintenanceTask).where(
                    MaintenanceTask.id == payload.task_id,
                    MaintenanceTask.organization_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    log = MaintenanceLog(organization_id=org_id, **payload.model_dump())
    db.add(log)

    # Advance the parent task's completion / next-due dates.
    if task is not None:
        completed_on = payload.service_date or date.today()
        task.last_completed_date = completed_on
        if task.status != "completed":
            task.status = "scheduled"
        cadence = _FREQUENCY_DAYS.get(task.frequency or "")
        if cadence:
            task.next_due_date = completed_on + timedelta(days=cadence)

    await db.commit()
    result = await db.execute(
        select(MaintenanceLog).options(*_LOG_OPTS).where(MaintenanceLog.id == log.id)
    )
    return LogResponse.model_validate(result.scalar_one())


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_log(
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    result = await db.execute(
        select(MaintenanceLog).where(
            MaintenanceLog.id == log_id,
            MaintenanceLog.organization_id == current_user.organization_id,
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")
    await db.delete(log)
    await db.commit()

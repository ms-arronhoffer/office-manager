"""Maintenance program — CRUD for assets, tasks and service logs.

Covers the six property-maintenance domains (HVAC, fire & life safety, plumbing
& backflow, refuse & waste, exterior & structural, elevators & lifts). Tasks
carry a due date, an optionally assigned vendor, and reminder settings; logging a
service visit advances the task's ``last_completed_date`` / ``next_due_date``.
"""
import uuid
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.maintenance import (
    MaintenanceAsset,
    MaintenanceCategoryTopicConfig,
    MaintenanceLog,
    MaintenanceTask,
    MAINTENANCE_CATEGORIES,
    MAINTENANCE_CATEGORY_KEYS,
    MAINTENANCE_FREQUENCIES,
    MAINTENANCE_ASSET_STATUSES,
    MAINTENANCE_TASK_STATUSES,
    default_subtopics_for_category,
)
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.user import User
from app.services.pm_service import generate_work_order_for_task

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
    auto_generate_work_order: bool = False
    work_order_lead_days: int = Field(default=0, ge=0, le=365)
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
    auto_generate_work_order: Optional[bool] = None
    work_order_lead_days: Optional[int] = Field(default=None, ge=0, le=365)
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
    auto_generate_work_order: bool = False
    work_order_lead_days: int = 0
    last_generated_due_date: Optional[date] = None
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


class CategorySubtopicUpdate(BaseModel):
    value: Optional[str] = None
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


class ComplianceCategoryStat(BaseModel):
    category: str
    label: str
    active: int
    overdue: int
    regulatory_active: int
    regulatory_overdue: int
    on_time_rate: float


class ComplianceResponse(BaseModel):
    # Active = not completed and has a due date.
    active_tasks: int
    overdue: int
    on_time: int
    on_time_rate: float
    regulatory_active: int
    regulatory_overdue: int
    regulatory_on_time_rate: float
    automation_enabled: int
    work_orders_generated: int
    by_category: list[ComplianceCategoryStat]


class CategorySubtopicsUpdate(BaseModel):
    subtopics: list[CategorySubtopicUpdate]


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


def _sanitize_subtopic_value(value: str) -> str:
    sanitized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized[:60]


def _subtopic_value_from_label(label: str) -> str:
    return _sanitize_subtopic_value(label)


def _normalize_subtopics(subtopics: list[CategorySubtopicUpdate]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen_values: set[str] = set()
    seen_labels: set[str] = set()
    for item in subtopics:
        label = item.label.strip()
        if not label:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Topic labels cannot be blank",
            )
        raw_value = (item.value or "").strip()
        value = _sanitize_subtopic_value(raw_value) if raw_value else _subtopic_value_from_label(label)
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Topic '{label}' must produce a valid key",
            )
        if value in seen_values:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate topic key: {value}",
            )
        lower_label = label.lower()
        if lower_label in seen_labels:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate topic label: {label}",
            )
        seen_values.add(value)
        seen_labels.add(lower_label)
        normalized.append({"value": value, "label": label})
    return normalized


def _build_category_info(category: str, subtopics: list[dict[str, str]]) -> CategoryInfo:
    return CategoryInfo(
        value=category,
        label=MAINTENANCE_CATEGORIES[category]["label"],
        subtopics=[CategorySubtopic(**item) for item in subtopics],
    )


async def _configured_subtopics_map(
    db: AsyncSession, organization_id: Optional[uuid.UUID]
) -> dict[str, list[dict[str, str]]]:
    if not organization_id:
        return {}
    result = await db.execute(
        select(MaintenanceCategoryTopicConfig).where(
            MaintenanceCategoryTopicConfig.organization_id == organization_id
        )
    )
    return {
        row.category: row.subtopics or []
        for row in result.scalars().all()
    }


async def _effective_subtopics(
    db: AsyncSession, organization_id: Optional[uuid.UUID], category: str
) -> list[dict[str, str]]:
    configured = await _configured_subtopics_map(db, organization_id)
    return configured.get(category, default_subtopics_for_category(category))


async def _validate_category(
    category: str,
    subtopic: Optional[str],
    db: AsyncSession,
    organization_id: Optional[uuid.UUID],
    *,
    current_category: Optional[str] = None,
    current_subtopic: Optional[str] = None,
) -> None:
    if category not in MAINTENANCE_CATEGORY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown maintenance category: {category}",
        )
    if subtopic is None:
        return
    if category == current_category and subtopic == current_subtopic:
        return
    allowed = {item["value"] for item in await _effective_subtopics(db, organization_id, category)}
    if subtopic not in allowed:
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
async def get_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    configured = await _configured_subtopics_map(db, current_user.organization_id)
    categories = [
        _build_category_info(key, configured.get(key, default_subtopics_for_category(key)))
        for key in MAINTENANCE_CATEGORIES
    ]
    return CatalogResponse(
        categories=categories,
        frequencies=list(MAINTENANCE_FREQUENCIES),
        task_statuses=list(MAINTENANCE_TASK_STATUSES),
        asset_statuses=list(MAINTENANCE_ASSET_STATUSES),
    )


@router.put("/categories/{category}/subtopics", response_model=CategoryInfo)
async def update_category_subtopics(
    category: str,
    payload: CategorySubtopicsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    if category not in MAINTENANCE_CATEGORY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown maintenance category: {category}",
        )
    normalized = _normalize_subtopics(payload.subtopics)
    defaults = default_subtopics_for_category(category)
    result = await db.execute(
        select(MaintenanceCategoryTopicConfig).where(
            MaintenanceCategoryTopicConfig.organization_id == current_user.organization_id,
            MaintenanceCategoryTopicConfig.category == category,
        )
    )
    config = result.scalar_one_or_none()
    if normalized == defaults:
        if config:
            await db.delete(config)
    else:
        if not config:
            config = MaintenanceCategoryTopicConfig(
                organization_id=current_user.organization_id,
                category=category,
                subtopics=normalized,
            )
            db.add(config)
        else:
            config.subtopics = normalized
    await db.commit()
    return _build_category_info(category, normalized)


@router.delete("/categories/{category}/subtopics", response_model=CategoryInfo)
async def reset_category_subtopics(
    category: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_editor(current_user)
    if category not in MAINTENANCE_CATEGORY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown maintenance category: {category}",
        )
    result = await db.execute(
        select(MaintenanceCategoryTopicConfig).where(
            MaintenanceCategoryTopicConfig.organization_id == current_user.organization_id,
            MaintenanceCategoryTopicConfig.category == category,
        )
    )
    config = result.scalar_one_or_none()
    if config:
        await db.delete(config)
        await db.commit()
    return _build_category_info(category, default_subtopics_for_category(category))


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


def _rate(numerator: int, denominator: int) -> float:
    """Percentage rounded to one decimal; 100.0 when nothing is tracked."""
    if denominator <= 0:
        return 100.0
    return round(numerator / denominator * 100, 1)


@router.get("/compliance", response_model=ComplianceResponse)
async def get_compliance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Preventive-maintenance compliance KPIs.

    "Active" tasks are those not yet completed that carry a due date. On-time
    means the due date has not passed. Regulatory tasks (fire/life-safety, ADA,
    elevator certifications, …) are reported separately so an FM can see at a
    glance whether any statutory obligation is overdue.
    """
    org_id = current_user.organization_id
    today = date.today()

    tasks = (
        await db.execute(
            select(MaintenanceTask).where(MaintenanceTask.organization_id == org_id)
        )
    ).scalars().all()

    def _is_active(t: MaintenanceTask) -> bool:
        return t.status != "completed" and t.next_due_date is not None

    def _is_overdue(t: MaintenanceTask) -> bool:
        return _is_active(t) and t.next_due_date < today

    active = [t for t in tasks if _is_active(t)]
    overdue = [t for t in active if _is_overdue(t)]
    reg_active = [t for t in active if t.is_regulatory]
    reg_overdue = [t for t in overdue if t.is_regulatory]

    by_category: list[ComplianceCategoryStat] = []
    for key, cat in MAINTENANCE_CATEGORIES.items():
        cat_active = [t for t in active if t.category == key]
        cat_overdue = [t for t in cat_active if _is_overdue(t)]
        cat_reg_active = [t for t in cat_active if t.is_regulatory]
        cat_reg_overdue = [t for t in cat_overdue if t.is_regulatory]
        by_category.append(
            ComplianceCategoryStat(
                category=key,
                label=cat["label"],
                active=len(cat_active),
                overdue=len(cat_overdue),
                regulatory_active=len(cat_reg_active),
                regulatory_overdue=len(cat_reg_overdue),
                on_time_rate=_rate(len(cat_active) - len(cat_overdue), len(cat_active)),
            )
        )

    automation_enabled = sum(1 for t in tasks if t.auto_generate_work_order)
    work_orders_generated = (
        await db.execute(
            select(func.count())
            .select_from(MaintenanceTicket)
            .where(
                MaintenanceTicket.organization_id == org_id,
                MaintenanceTicket.source_task_id.is_not(None),
                MaintenanceTicket.is_deleted.is_(False),
            )
        )
    ).scalar_one()

    return ComplianceResponse(
        active_tasks=len(active),
        overdue=len(overdue),
        on_time=len(active) - len(overdue),
        on_time_rate=_rate(len(active) - len(overdue), len(active)),
        regulatory_active=len(reg_active),
        regulatory_overdue=len(reg_overdue),
        regulatory_on_time_rate=_rate(
            len(reg_active) - len(reg_overdue), len(reg_active)
        ),
        automation_enabled=automation_enabled,
        work_orders_generated=work_orders_generated,
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
    await _validate_category(
        payload.category, payload.subtopic, db, current_user.organization_id
    )
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
        await _validate_category(
            new_category,
            new_subtopic,
            db,
            current_user.organization_id,
            current_category=asset.category,
            current_subtopic=asset.subtopic,
        )
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
    await _validate_category(
        payload.category, payload.subtopic, db, current_user.organization_id
    )
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
        await _validate_category(
            new_category,
            new_subtopic,
            db,
            current_user.organization_id,
            current_category=task.category,
            current_subtopic=task.subtopic,
        )
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


class GenerateWorkOrderResponse(BaseModel):
    ticket_id: Optional[uuid.UUID] = None
    created: bool
    detail: str


@router.post(
    "/tasks/{task_id}/generate-work-order",
    response_model=GenerateWorkOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_task_work_order(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """On-demand: spawn a preventive-maintenance work order for a task now.

    Mirrors the nightly automation but lets an editor create the work order
    immediately. De-duplicates against the task's current due cycle so repeated
    clicks don't pile up duplicate tickets.
    """
    _require_editor(current_user)
    result = await db.execute(
        select(MaintenanceTask)
        .where(
            MaintenanceTask.id == task_id,
            MaintenanceTask.organization_id == current_user.organization_id,
        )
        .with_for_update()
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task.next_due_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task has no due date to generate a work order for",
        )
    if task.last_generated_due_date == task.next_due_date:
        return GenerateWorkOrderResponse(
            created=False,
            detail="A work order has already been generated for the current due cycle.",
        )

    ticket = await generate_work_order_for_task(
        db, task, created_by_id=current_user.id
    )
    if ticket is None:
        # Build the message before any rollback-poisoning side effects.
        reason = (
            "Task has no assigned office."
            if task.office_id is None
            else "No eligible user found to own the work order."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to generate work order. {reason}",
        )

    await db.commit()
    return GenerateWorkOrderResponse(
        ticket_id=ticket.id,
        created=True,
        detail="Work order created.",
    )


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

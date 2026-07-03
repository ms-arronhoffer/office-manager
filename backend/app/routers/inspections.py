"""Property inspections API router (Phase 1.5) — `/api/v1/inspections`.

Reusable inspection checklists (templates) and the inspections performed against
an office. Reads are available to any authenticated org user; creating and
editing templates/inspections requires ``admin`` or ``editor``. Photos attach
through the generic attachments API with ``entity_type="inspection"``.

Workflow:
  1. Build a template: ``POST /templates`` with checklist items.
  2. Start an inspection: ``POST /`` (optionally from a template — its items are
     snapshotted onto the inspection as blank results).
  3. Record results: ``PATCH /{id}`` sets each item's pass/fail/na + notes.
  4. ``POST /{id}/complete`` locks the inspection and computes its overall result.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.inspection import (
    INSPECTION_STATUSES,
    Inspection,
    InspectionItemResult,
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.models.office import Office
from app.models.user import User
from app.services import inspection_service as svc
from app.services.inspection_service import InspectionError

router = APIRouter()

# Editors and admins may create/modify; everyone in the org may read.
Editor = require_role("admin", "editor")


# ─── Schemas ────────────────────────────────────────────────────────────────

class TemplateItemInput(BaseModel):
    label: str
    description: str | None = None
    sort_order: int = 0
    is_required: bool = True


class TemplateCreate(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    is_active: bool = True
    items: list[TemplateItemInput] = []


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    is_active: bool | None = None
    items: list[TemplateItemInput] | None = None


class TemplateItemResponse(BaseModel):
    id: uuid.UUID
    label: str
    description: str | None
    sort_order: int
    is_required: bool

    model_config = {"from_attributes": True}


class TemplateResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    category: str | None
    is_active: bool
    items: list[TemplateItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InspectionCreate(BaseModel):
    office_id: uuid.UUID
    title: str
    template_id: uuid.UUID | None = None
    scheduled_date: date | None = None
    notes: str | None = None


class ItemResultInput(BaseModel):
    id: uuid.UUID
    result: str | None = None
    notes: str | None = None


class InspectionUpdate(BaseModel):
    title: str | None = None
    scheduled_date: date | None = None
    status: str | None = None
    notes: str | None = None
    results: list[ItemResultInput] | None = None


class ItemResultResponse(BaseModel):
    id: uuid.UUID
    template_item_id: uuid.UUID | None
    label: str
    sort_order: int
    is_required: bool
    result: str | None
    notes: str | None

    model_config = {"from_attributes": True}


class InspectionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    template_id: uuid.UUID | None
    office_id: uuid.UUID
    title: str
    status: str
    scheduled_date: date | None
    completed_at: datetime | None
    inspector_id: uuid.UUID | None
    overall_result: str | None
    notes: str | None
    results: list[ItemResultResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_office(db: AsyncSession, office_id: uuid.UUID, org_id) -> Office:
    office = (
        await db.execute(
            select(Office.id).where(
                Office.id == office_id,
                Office.organization_id == org_id,
                Office.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not office:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found")
    return office


async def _load_template(db: AsyncSession, template_id: uuid.UUID, org_id) -> InspectionTemplate:
    db.expunge_all()
    template = await svc.get_template(db, template_id, org_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


async def _load_inspection(db: AsyncSession, inspection_id: uuid.UUID, org_id) -> Inspection:
    db.expunge_all()
    inspection = await svc.get_inspection(db, inspection_id, org_id)
    if not inspection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
    return inspection


def _set_template_items(template: InspectionTemplate, items: list[TemplateItemInput]) -> None:
    template.items.clear()
    for idx, item in enumerate(items):
        template.items.append(
            InspectionTemplateItem(
                label=item.label,
                description=item.description,
                sort_order=item.sort_order if item.sort_order else idx,
                is_required=item.is_required,
            )
        )


# ─── Template endpoints ───────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(InspectionTemplate)
        .where(InspectionTemplate.organization_id == current_user.organization_id)
        .options(selectinload(InspectionTemplate.items))
        .order_by(InspectionTemplate.name)
    )
    if active_only:
        stmt = stmt.where(InspectionTemplate.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_template(db, template_id, current_user.organization_id)


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    template = InspectionTemplate(
        organization_id=current_user.organization_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        is_active=payload.is_active,
    )
    _set_template_items(template, payload.items)
    db.add(template)
    await db.commit()
    return await _load_template(db, template.id, current_user.organization_id)


@router.patch("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    template = await _load_template(db, template_id, org_id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "description", "category", "is_active"):
        if field in data:
            setattr(template, field, data[field])
    if payload.items is not None:
        _set_template_items(template, payload.items)
    await db.commit()
    return await _load_template(db, template.id, org_id)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    template = await _load_template(db, template_id, current_user.organization_id)
    await db.delete(template)
    await db.commit()


# ─── Inspection endpoints ─────────────────────────────────────────────────────

@router.get("", response_model=list[InspectionResponse])
async def list_inspections(
    office_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Inspection)
        .where(Inspection.organization_id == current_user.organization_id)
        .options(selectinload(Inspection.results))
        .order_by(Inspection.scheduled_date.desc().nullslast(), Inspection.created_at.desc())
    )
    if office_id:
        stmt = stmt.where(Inspection.office_id == office_id)
    if status_filter:
        stmt = stmt.where(Inspection.status == status_filter)
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


@router.get("/{inspection_id}", response_model=InspectionResponse)
async def get_inspection(
    inspection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_inspection(db, inspection_id, current_user.organization_id)


@router.post("", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED)
async def create_inspection(
    payload: InspectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    await _get_office(db, payload.office_id, org_id)

    inspection = Inspection(
        organization_id=org_id,
        template_id=payload.template_id,
        office_id=payload.office_id,
        title=payload.title,
        scheduled_date=payload.scheduled_date,
        notes=payload.notes,
        status="scheduled",
        inspector_id=current_user.id,
    )
    if payload.template_id:
        template = await _load_template(db, payload.template_id, org_id)
        inspection.results = svc.snapshot_items(template)
    db.add(inspection)
    await db.commit()
    return await _load_inspection(db, inspection.id, org_id)


@router.patch("/{inspection_id}", response_model=InspectionResponse)
async def update_inspection(
    inspection_id: uuid.UUID,
    payload: InspectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    inspection = await _load_inspection(db, inspection_id, org_id)
    if inspection.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A completed inspection can no longer be edited.",
        )

    data = payload.model_dump(exclude_unset=True)
    for field in ("title", "scheduled_date", "notes"):
        if field in data:
            setattr(inspection, field, data[field])
    if "status" in data:
        if data["status"] not in INSPECTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status must be one of: {', '.join(sorted(INSPECTION_STATUSES))}.",
            )
        # Completion is handled by the dedicated endpoint so results are scored.
        if data["status"] == "completed":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Use POST /{id}/complete to complete an inspection.",
            )
        inspection.status = data["status"]

    if payload.results is not None:
        by_id = {r.id: r for r in inspection.results}
        try:
            for update in payload.results:
                item = by_id.get(update.id)
                if item is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Result item {update.id} not found on this inspection.",
                    )
                fields = update.model_dump(exclude_unset=True)
                if "result" in fields:
                    item.result = svc.validate_result(update.result)
                if "notes" in fields:
                    item.notes = update.notes
        except InspectionError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            )
        if inspection.status == "scheduled":
            inspection.status = "in_progress"

    await db.commit()
    return await _load_inspection(db, inspection.id, org_id)


@router.post("/{inspection_id}/complete", response_model=InspectionResponse)
async def complete_inspection(
    inspection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    """Lock an inspection and compute its overall pass/fail result."""
    org_id = current_user.organization_id
    inspection = await _load_inspection(db, inspection_id, org_id)
    if inspection.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Inspection is already completed."
        )
    if not svc.required_items_scored(inspection):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All required checklist items must be scored before completing.",
        )
    inspection.status = "completed"
    inspection.completed_at = datetime.now(timezone.utc)
    inspection.overall_result = svc.compute_overall_result(inspection)
    await db.commit()
    return await _load_inspection(db, inspection.id, org_id)


@router.delete("/{inspection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inspection(
    inspection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    inspection = await _load_inspection(db, inspection_id, current_user.organization_id)
    await db.delete(inspection)
    await db.commit()

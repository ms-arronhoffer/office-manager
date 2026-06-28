import math
import uuid
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.transition import OfficeTransition, TransitionChecklistItem
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.transition import (
    ChecklistItemCreate,
    ChecklistItemResponse,
    ChecklistItemUpdate,
    TransitionCreate,
    TransitionResponse,
    TransitionUpdate,
)
from app.services.activity_service import log_activity, compute_changes
from app.services.webhook_service import dispatch_webhook
from app.services import usage_service
from app.utils.sorting import apply_sorting

router = APIRouter()


@router.get("/export")
async def export_transitions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(OfficeTransition).where(OfficeTransition.is_deleted.is_(False)).where(OfficeTransition.organization_id == current_user.organization_id).order_by(OfficeTransition.created_at.desc())
    )
    transitions = result.scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Office #", "Type", "Status", "Address", "New Address", "Sheet Name", "Created At"])
    for t in transitions:
        writer.writerow([
            t.office_number, t.transition_type, t.status, t.address,
            t.new_address, t.sheet_name, t.created_at,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transitions.csv"},
    )


@router.get("", response_model=PaginatedResponse[TransitionResponse])
async def list_transitions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    transition_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = select(OfficeTransition).options(joinedload(OfficeTransition.checklist_items)).where(OfficeTransition.is_deleted.is_(False))
    base = base.where(OfficeTransition.organization_id == current_user.organization_id)

    if transition_type is not None:
        base = base.where(OfficeTransition.transition_type == transition_type)
    if status_filter is not None:
        base = base.where(OfficeTransition.status == status_filter)

    count_stmt = select(func.count()).select_from(
        base.with_only_columns(OfficeTransition.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _TRANSITION_SORT_COLS = {
        "transition_type": OfficeTransition.transition_type,
        "status": OfficeTransition.status,
        "created_at": OfficeTransition.created_at,
    }
    stmt = apply_sorting(base, sort_by, sort_order, _TRANSITION_SORT_COLS, [OfficeTransition.created_at.desc()])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    transitions = result.scalars().unique().all()

    return PaginatedResponse(
        items=[TransitionResponse.model_validate(t, from_attributes=True) for t in transitions],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{transition_id}", response_model=TransitionResponse)
async def get_transition(
    transition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(OfficeTransition)
        .options(joinedload(OfficeTransition.checklist_items))
        .where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(False), OfficeTransition.organization_id == current_user.organization_id)
    )
    transition = result.unique().scalar_one_or_none()
    if not transition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transition not found")
    return TransitionResponse.model_validate(transition, from_attributes=True)


@router.post("", response_model=TransitionResponse, status_code=status.HTTP_201_CREATED)
async def create_transition(
    payload: TransitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    transition = OfficeTransition(**payload.model_dump(), organization_id=current_user.organization_id)
    db.add(transition)
    await db.commit()
    await db.refresh(transition)
    await log_activity(db, user=current_user, action="created", entity_type="transition", entity_id=transition.id, entity_label=transition.sheet_name or f"Office #{transition.office_number}")
    await usage_service.record_event(db, current_user.organization_id, "transition_created")

    result = await db.execute(
        select(OfficeTransition)
        .options(joinedload(OfficeTransition.checklist_items))
        .where(OfficeTransition.id == transition.id)
    )
    return TransitionResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.put("/{transition_id}", response_model=TransitionResponse)
async def update_transition(
    transition_id: uuid.UUID,
    payload: TransitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(OfficeTransition).where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(False), OfficeTransition.organization_id == current_user.organization_id))
    transition = result.scalar_one_or_none()
    if not transition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transition not found")

    update_data = payload.model_dump(exclude_unset=True)
    old_values = {k: getattr(transition, k) for k in update_data}
    old_status = transition.status
    for field, value in update_data.items():
        setattr(transition, field, value)

    await db.commit()
    changes = compute_changes(old_values, update_data)
    await log_activity(db, user=current_user, action="updated", entity_type="transition", entity_id=transition.id, entity_label=transition.sheet_name or f"Office #{transition.office_number}", changes=changes)

    # Dispatch transition.completed webhook when status first becomes "completed"
    if old_status != "completed" and transition.status == "completed":
        try:
            await dispatch_webhook(
                db,
                transition.organization_id,
                "transition.completed",
                {
                    "transition_id": str(transition.id),
                    "sheet_name": transition.sheet_name,
                    "office_number": transition.office_number,
                },
            )
        except Exception:
            pass

    result = await db.execute(
        select(OfficeTransition)
        .options(joinedload(OfficeTransition.checklist_items))
        .where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(False))
    )
    return TransitionResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.delete("/{transition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transition(
    transition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(OfficeTransition).where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(False), OfficeTransition.organization_id == current_user.organization_id))
    transition = result.scalar_one_or_none()
    if not transition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transition not found")
    label = transition.sheet_name or f"Office #{transition.office_number}"
    transition.is_deleted = True
    transition.deleted_at = _utcnow()
    await db.commit()
    await log_activity(db, user=current_user, action="deleted", entity_type="transition", entity_id=transition_id, entity_label=label)


@router.patch("/{transition_id}/restore", response_model=TransitionResponse)
async def restore_transition(
    transition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(OfficeTransition).where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(True), OfficeTransition.organization_id == current_user.organization_id))
    transition = result.scalar_one_or_none()
    if not transition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transition not found or not deleted")
    transition.is_deleted = False
    transition.deleted_at = None
    await db.commit()
    label = transition.sheet_name or f"Office #{transition.office_number}"
    await log_activity(db, user=current_user, action="updated", entity_type="transition", entity_id=transition_id, entity_label=label)
    result = await db.execute(
        select(OfficeTransition)
        .options(joinedload(OfficeTransition.checklist_items))
        .where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(False))
    )
    return TransitionResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


# ---------------------------------------------------------------------------
# Checklist sub-resource
# ---------------------------------------------------------------------------

@router.post(
    "/{transition_id}/checklist",
    response_model=ChecklistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_checklist_item(
    transition_id: uuid.UUID,
    payload: ChecklistItemCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(OfficeTransition).where(OfficeTransition.id == transition_id, OfficeTransition.is_deleted.is_(False)))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transition not found")

    # Next sort order
    order_result = await db.execute(
        select(func.coalesce(func.max(TransitionChecklistItem.sort_order), 0)).where(
            TransitionChecklistItem.transition_id == transition_id
        )
    )
    next_order = order_result.scalar_one() + 1

    item = TransitionChecklistItem(
        transition_id=transition_id,
        sort_order=next_order,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ChecklistItemResponse.model_validate(item, from_attributes=True)


@router.put(
    "/{transition_id}/checklist/{item_id}",
    response_model=ChecklistItemResponse,
)
async def update_checklist_item(
    transition_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ChecklistItemUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(TransitionChecklistItem).where(
            TransitionChecklistItem.id == item_id,
            TransitionChecklistItem.transition_id == transition_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return ChecklistItemResponse.model_validate(item, from_attributes=True)


@router.patch(
    "/{transition_id}/checklist/{item_id}/toggle",
    response_model=ChecklistItemResponse,
)
async def toggle_checklist_item(
    transition_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(TransitionChecklistItem).where(
            TransitionChecklistItem.id == item_id,
            TransitionChecklistItem.transition_id == transition_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")

    item.is_complete = not item.is_complete
    await db.commit()
    await db.refresh(item)
    return ChecklistItemResponse.model_validate(item, from_attributes=True)

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.office import Office as OfficeModel
from app.models.ticket_template import TicketTemplate
from app.models.user import User
from app.schemas.ticket_template import TicketTemplateCreate, TicketTemplateUpdate, TicketTemplateResponse
from app.utils.tenant_scope import load_or_404

router = APIRouter()

_LOAD_OPTIONS = [
    joinedload(TicketTemplate.category),
    joinedload(TicketTemplate.office).joinedload(OfficeModel.manager),
    joinedload(TicketTemplate.assigned_to),
]


@router.get("", response_model=list[TicketTemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TicketTemplate)
        .options(*_LOAD_OPTIONS)
        .where(TicketTemplate.organization_id == current_user.organization_id)
        .order_by(TicketTemplate.name)
    )
    return [TicketTemplateResponse.model_validate(t, from_attributes=True) for t in result.scalars().unique().all()]


@router.post("", response_model=TicketTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TicketTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    template = TicketTemplate(
        organization_id=current_user.organization_id, **payload.model_dump()
    )
    db.add(template)
    await db.commit()
    result = await db.execute(
        select(TicketTemplate)
        .options(*_LOAD_OPTIONS)
        .where(
            TicketTemplate.id == template.id,
            TicketTemplate.organization_id == current_user.organization_id,
        )
    )
    return TicketTemplateResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.put("/{template_id}", response_model=TicketTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: TicketTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    template = await load_or_404(
        db,
        TicketTemplate,
        template_id,
        current_user.organization_id,
        detail="Template not found",
    )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    await db.commit()
    result = await db.execute(
        select(TicketTemplate)
        .options(*_LOAD_OPTIONS)
        .where(
            TicketTemplate.id == template_id,
            TicketTemplate.organization_id == current_user.organization_id,
        )
    )
    return TicketTemplateResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    template = await load_or_404(
        db,
        TicketTemplate,
        template_id,
        current_user.organization_id,
        detail="Template not found",
    )
    await db.delete(template)
    await db.commit()


class BulkCreatePayload(BaseModel):
    office_ids: list[uuid.UUID]


@router.post("/{template_id}/bulk-create")
async def bulk_create_from_template(
    template_id: uuid.UUID,
    payload: BulkCreatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    template = await load_or_404(
        db,
        TicketTemplate,
        template_id,
        current_user.organization_id,
        detail="Template not found",
    )
    if not template.category_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template must have a category set before bulk-creating tickets",
        )
    if not payload.office_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No office IDs provided")

    ticket_ids = []
    for office_id in payload.office_ids:
        ticket = MaintenanceTicket(
            subject=template.subject,
            description=template.description or "",
            priority=template.priority,
            status="open",
            category_id=template.category_id,
            office_id=office_id,
            assigned_to_id=template.assigned_to_id,
            created_by_id=current_user.id,
        )
        db.add(ticket)
        ticket_ids.append(ticket.id)

    await db.commit()
    return {"created": len(ticket_ids), "ticket_ids": [str(t) for t in ticket_ids]}

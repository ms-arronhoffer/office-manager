import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.user import User
from app.schemas.maintenance_ticket import TicketCategoryCreate, TicketCategoryResponse
from app.utils.tenant_scope import load_or_404

router = APIRouter()


@router.get("", response_model=list[TicketCategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(TicketCategory).where(TicketCategory.organization_id == current_user.organization_id).order_by(TicketCategory.name))
    return [TicketCategoryResponse.model_validate(c, from_attributes=True) for c in result.scalars().all()]


@router.post("", response_model=TicketCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: TicketCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    existing = await db.execute(
        select(TicketCategory).where(
            TicketCategory.name == payload.name.strip(),
            TicketCategory.organization_id == current_user.organization_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category already exists")

    category = TicketCategory(name=payload.name.strip(), organization_id=current_user.organization_id)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return TicketCategoryResponse.model_validate(category, from_attributes=True)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    category = await load_or_404(
        db,
        TicketCategory,
        category_id,
        current_user.organization_id,
        detail="Category not found",
    )

    ticket_count = (
        await db.execute(
            select(func.count(MaintenanceTicket.id)).where(
                MaintenanceTicket.category_id == category_id
            )
        )
    ).scalar_one()

    if ticket_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete category with {ticket_count} existing ticket(s)",
        )

    await db.delete(category)
    await db.commit()

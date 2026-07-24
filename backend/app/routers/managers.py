import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.office import Manager
from app.models.user import User
from app.schemas.office import ManagerCreate, ManagerResponse, ManagerUpdate
from app.utils.tenant_scope import load_or_404

router = APIRouter()


@router.get("", response_model=list[ManagerResponse])
async def list_managers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Manager)
        .where(Manager.organization_id == current_user.organization_id)
        .order_by(Manager.name)
    )
    return result.scalars().all()


@router.post("", response_model=ManagerResponse, status_code=status.HTTP_201_CREATED)
async def create_manager(
    payload: ManagerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    manager = Manager(organization_id=current_user.organization_id, **payload.model_dump())
    name = manager.name
    db.add(manager)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A manager named '{name}' already exists.",
        )
    await db.refresh(manager)
    return ManagerResponse.model_validate(manager, from_attributes=True)


@router.put("/{manager_id}", response_model=ManagerResponse)
async def update_manager(
    manager_id: uuid.UUID,
    payload: ManagerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    manager = await load_or_404(
        db, Manager, manager_id, current_user.organization_id, detail="Manager not found"
    )

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(manager, field, value)
    name = updates.get("name", manager.name)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A manager named '{name}' already exists.",
        )
    await db.refresh(manager)
    return ManagerResponse.model_validate(manager, from_attributes=True)


@router.delete("/{manager_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_manager(
    manager_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    manager = await load_or_404(
        db, Manager, manager_id, current_user.organization_id, detail="Manager not found"
    )
    await db.delete(manager)
    await db.commit()

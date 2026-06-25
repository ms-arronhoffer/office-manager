import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.entity_contact import EntityContact, ENTITY_CONTACT_TYPES
from app.models.user import User
from app.schemas.entity_contact import (
    EntityContactCreate,
    EntityContactResponse,
    EntityContactUpdate,
)

router = APIRouter()


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in ENTITY_CONTACT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported entity_type '{entity_type}'. Allowed: {', '.join(ENTITY_CONTACT_TYPES)}",
        )


@router.get("", response_model=list[EntityContactResponse])
async def list_contacts(
    entity_type: str = Query(...),
    entity_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_entity_type(entity_type)
    result = await db.execute(
        select(EntityContact)
        .where(
            EntityContact.entity_type == entity_type,
            EntityContact.entity_id == entity_id,
            EntityContact.organization_id == current_user.organization_id,
        )
        .order_by(EntityContact.is_primary.desc(), EntityContact.contact_name)
    )
    contacts = result.scalars().all()
    return [EntityContactResponse.model_validate(c, from_attributes=True) for c in contacts]


@router.post("", response_model=EntityContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: EntityContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    _validate_entity_type(payload.entity_type)
    contact = EntityContact(**payload.model_dump(), organization_id=current_user.organization_id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return EntityContactResponse.model_validate(contact, from_attributes=True)


async def _load(db: AsyncSession, contact_id: uuid.UUID, org_id: uuid.UUID) -> EntityContact:
    result = await db.execute(
        select(EntityContact).where(
            EntityContact.id == contact_id,
            EntityContact.organization_id == org_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.put("/{contact_id}", response_model=EntityContactResponse)
async def update_contact(
    contact_id: uuid.UUID,
    payload: EntityContactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    contact = await _load(db, contact_id, current_user.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    await db.commit()
    await db.refresh(contact)
    return EntityContactResponse.model_validate(contact, from_attributes=True)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    contact = await _load(db, contact_id, current_user.organization_id)
    await db.delete(contact)
    await db.commit()

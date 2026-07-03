"""Custom lease template API router — ``/api/v1/lease-templates``.

Org-scoped, reusable lease document bodies (with ``{{merge_field}}`` placeholders)
that standardise the leases staff send to residents and drive the resident-lease
e-signing engine. Reads are open to any authenticated org user; writes require
``admin``/``editor`` and deletes require ``admin`` (mirroring the leasing router).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.lease_template import LeaseTemplate
from app.models.user import User

router = APIRouter()

Editor = require_role("admin", "editor")
Admin = require_role("admin")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class LeaseTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    body: str
    is_default: bool = False
    is_active: bool = True


class LeaseTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    body: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class LeaseTemplateResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    body: str
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_template(db: AsyncSession, template_id: uuid.UUID, org_id) -> LeaseTemplate:
    tmpl = (
        await db.execute(
            select(LeaseTemplate).where(
                LeaseTemplate.id == template_id,
                LeaseTemplate.organization_id == org_id,
                LeaseTemplate.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease template not found")
    return tmpl


async def _clear_other_defaults(
    db: AsyncSession, org_id, *, keep_id: uuid.UUID | None = None
) -> None:
    """Ensure at most one default template per organisation."""
    stmt = select(LeaseTemplate).where(
        LeaseTemplate.organization_id == org_id,
        LeaseTemplate.is_deleted.is_(False),
        LeaseTemplate.is_default.is_(True),
    )
    if keep_id is not None:
        stmt = stmt.where(LeaseTemplate.id != keep_id)
    for other in (await db.execute(stmt)).scalars().all():
        other.is_default = False


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[LeaseTemplateResponse])
async def list_templates(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(LeaseTemplate)
        .where(
            LeaseTemplate.organization_id == current_user.organization_id,
            LeaseTemplate.is_deleted.is_(False),
        )
        .order_by(LeaseTemplate.is_default.desc(), LeaseTemplate.name)
    )
    if active_only:
        stmt = stmt.where(LeaseTemplate.is_active.is_(True))
    result = await db.execute(stmt)
    return [LeaseTemplateResponse.model_validate(t) for t in result.scalars().all()]


@router.post("", response_model=LeaseTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: LeaseTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    tmpl = LeaseTemplate(organization_id=org_id, **payload.model_dump())
    if tmpl.is_default:
        await _clear_other_defaults(db, org_id)
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return LeaseTemplateResponse.model_validate(tmpl)


@router.get("/{template_id}", response_model=LeaseTemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tmpl = await _get_template(db, template_id, current_user.organization_id)
    return LeaseTemplateResponse.model_validate(tmpl)


@router.patch("/{template_id}", response_model=LeaseTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: LeaseTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    tmpl = await _get_template(db, template_id, org_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default") is True:
        await _clear_other_defaults(db, org_id, keep_id=tmpl.id)
    for field, value in data.items():
        setattr(tmpl, field, value)
    await db.commit()
    await db.refresh(tmpl)
    return LeaseTemplateResponse.model_validate(tmpl)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    tmpl = await _get_template(db, template_id, current_user.organization_id)
    tmpl.is_deleted = True
    tmpl.deleted_at = datetime.now(timezone.utc)
    await db.commit()

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


# A complete, ready-to-modify residential lease body that exercises every merge
# field exposed by ``leasing_funnel_service.build_lease_merge_context``. Staff can
# start from this sample (via ``GET /lease-templates/sample``) and edit it rather
# than authoring a lease from scratch, ensuring every dynamically-allocated field
# is present in the document.
SAMPLE_LEASE_NAME = "Standard Residential Lease Agreement"
SAMPLE_LEASE_DESCRIPTION = (
    "A full sample residential lease you can modify. Every field is filled from "
    "the lease record via merge fields, so nothing is missed."
)
SAMPLE_LEASE_BODY = """\
RESIDENTIAL LEASE AGREEMENT

This Residential Lease Agreement ("Agreement") is made on {{date}} between
{{organization_name}} ("Landlord") and {{tenant_names}} ("Tenant").

1. PREMISES
   The Landlord agrees to rent to the Tenant the residential premises located at
   {{property_address}} (Unit {{unit_number}} — {{unit_name}}) (the "Premises").

2. TERM
   This Agreement is a {{lease_type}} lease beginning on {{lease_start}} and
   ending on {{lease_end}}, unless terminated earlier in accordance with its
   terms.

3. RENT
   The Tenant shall pay rent of {{rent_amount}} per {{rent_frequency}}, due on
   the first day of each rental period, without demand, at the address designated
   by the Landlord.

4. SECURITY DEPOSIT
   Upon signing this Agreement, the Tenant shall pay a security deposit of
   {{security_deposit}}, to be held and returned in accordance with applicable
   law.

5. PET DEPOSIT
   A pet deposit of {{pet_deposit}} is required for any authorized pet kept on
   the Premises.

6. USE OF PREMISES
   The Premises shall be used solely as a private residence for the Tenant and
   the occupants named in this Agreement. The primary occupant of record is
   {{tenant_name}}.

7. MAINTENANCE
   The Tenant shall keep the Premises clean and in good condition and shall
   promptly notify the Landlord of any needed repairs.

8. GOVERNING LAW
   This Agreement shall be governed by the laws of the jurisdiction in which the
   Premises are located.

9. ENTIRE AGREEMENT
   This Agreement, titled "{{lease_name}}", constitutes the entire agreement
   between the parties and supersedes any prior understandings.

IN WITNESS WHEREOF, the parties have executed this Agreement as of {{date}}.

Landlord: {{organization_name}}

Tenant(s): {{tenant_names}}
"""


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


class LeaseTemplateSample(BaseModel):
    """A ready-to-modify sample lease used to seed the create form."""

    name: str
    description: str
    body: str


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


@router.get("/sample", response_model=LeaseTemplateSample)
async def get_sample_template(
    current_user: User = Depends(get_current_user),
):
    """Return a full, ready-to-modify sample lease to seed a new template."""
    return LeaseTemplateSample(
        name=SAMPLE_LEASE_NAME,
        description=SAMPLE_LEASE_DESCRIPTION,
        body=SAMPLE_LEASE_BODY,
    )


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

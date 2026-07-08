"""Custom application template API router — ``/api/v1/application-templates``.

Org-scoped, reusable rental-application documents (with ``{{merge_field}}``
placeholders and an optional structured ``field_schema``) that standardise the
applications staff send to prospects and drive the single-signer application
e-signing engine. Reads are open to any authenticated org user; writes require
``admin``/``editor`` and deletes require ``admin`` (mirroring the lease-template
router).
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
from app.models.application_template import ApplicationTemplate
from app.models.user import User

router = APIRouter()

Editor = require_role("admin", "editor")
Admin = require_role("admin")


# A complete, ready-to-modify residential application body that exercises the
# applicant merge fields exposed by
# ``leasing_funnel_service.build_application_merge_context``, plus a starter set of
# structured fields. Staff can start from this sample (via
# ``GET /application-templates/sample``) rather than authoring one from scratch.
SAMPLE_APPLICATION_NAME = "Standard Residential Rental Application"
SAMPLE_APPLICATION_DESCRIPTION = (
    "A full sample residential rental application you can modify. Applicant fields "
    "are filled from the application record via merge fields."
)
SAMPLE_APPLICATION_BODY = """\
RESIDENTIAL RENTAL APPLICATION

Applicant: {{applicant_name}}
Email: {{applicant_email}}
Phone: {{applicant_phone}}
Desired move-in date: {{desired_move_in}}
Stated monthly income: {{monthly_income}}

Submitted to {{organization_name}} on {{date}}.

1. APPLICANT REPRESENTATIONS
   The applicant certifies that the information provided in this application and
   in the fields below is true and complete. The applicant authorizes
   {{organization_name}} to verify this information and to obtain consumer,
   credit, criminal, and rental-history reports for the purpose of evaluating
   this application.

2. FEES
   Any application fee is non-refundable and is used to defray the cost of
   processing this application.

3. AUTHORIZATION
   By signing electronically below, the applicant consents to the collection and
   verification of the information provided and to tenant screening as described
   above.
"""

# The structured fields the applicant fills in on the public application page.
SAMPLE_APPLICATION_FIELD_SCHEMA = [
    {"key": "current_address", "label": "Current address", "type": "text", "required": True},
    {"key": "employer", "label": "Employer", "type": "text", "required": False},
    {"key": "employment_length", "label": "Length of employment", "type": "text", "required": False},
    {"key": "prior_address", "label": "Prior address", "type": "text", "required": False},
    {"key": "reference_name", "label": "Reference name", "type": "text", "required": False},
    {"key": "reference_phone", "label": "Reference phone", "type": "text", "required": False},
    {"key": "pets", "label": "Pets (type/number)", "type": "text", "required": False},
    {"key": "vehicles", "label": "Vehicles (make/model/plate)", "type": "textarea", "required": False},
]


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ApplicationTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    body: str
    field_schema: list | None = None
    is_default: bool = False
    is_active: bool = True


class ApplicationTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    body: str | None = None
    field_schema: list | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class ApplicationTemplateResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    body: str
    field_schema: list | None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplicationTemplateSample(BaseModel):
    """A ready-to-modify sample application used to seed the create form."""

    name: str
    description: str
    body: str
    field_schema: list


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_template(
    db: AsyncSession, template_id: uuid.UUID, org_id
) -> ApplicationTemplate:
    tmpl = (
        await db.execute(
            select(ApplicationTemplate).where(
                ApplicationTemplate.id == template_id,
                ApplicationTemplate.organization_id == org_id,
                ApplicationTemplate.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not tmpl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Application template not found"
        )
    return tmpl


async def _clear_other_defaults(
    db: AsyncSession, org_id, *, keep_id: uuid.UUID | None = None
) -> None:
    """Ensure at most one default template per organisation."""
    stmt = select(ApplicationTemplate).where(
        ApplicationTemplate.organization_id == org_id,
        ApplicationTemplate.is_deleted.is_(False),
        ApplicationTemplate.is_default.is_(True),
    )
    if keep_id is not None:
        stmt = stmt.where(ApplicationTemplate.id != keep_id)
    for other in (await db.execute(stmt)).scalars().all():
        other.is_default = False


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ApplicationTemplateResponse])
async def list_templates(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(ApplicationTemplate)
        .where(
            ApplicationTemplate.organization_id == current_user.organization_id,
            ApplicationTemplate.is_deleted.is_(False),
        )
        .order_by(ApplicationTemplate.is_default.desc(), ApplicationTemplate.name)
    )
    if active_only:
        stmt = stmt.where(ApplicationTemplate.is_active.is_(True))
    result = await db.execute(stmt)
    return [ApplicationTemplateResponse.model_validate(t) for t in result.scalars().all()]


@router.post("", response_model=ApplicationTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: ApplicationTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    org_id = current_user.organization_id
    tmpl = ApplicationTemplate(organization_id=org_id, **payload.model_dump())
    if tmpl.is_default:
        await _clear_other_defaults(db, org_id)
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return ApplicationTemplateResponse.model_validate(tmpl)


@router.get("/sample", response_model=ApplicationTemplateSample)
async def get_sample_template(
    current_user: User = Depends(get_current_user),
):
    """Return a full, ready-to-modify sample application to seed a new template."""
    return ApplicationTemplateSample(
        name=SAMPLE_APPLICATION_NAME,
        description=SAMPLE_APPLICATION_DESCRIPTION,
        body=SAMPLE_APPLICATION_BODY,
        field_schema=SAMPLE_APPLICATION_FIELD_SCHEMA,
    )


@router.get("/{template_id}", response_model=ApplicationTemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tmpl = await _get_template(db, template_id, current_user.organization_id)
    return ApplicationTemplateResponse.model_validate(tmpl)


@router.patch("/{template_id}", response_model=ApplicationTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: ApplicationTemplateUpdate,
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
    return ApplicationTemplateResponse.model_validate(tmpl)


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

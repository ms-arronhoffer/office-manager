"""Email customisation API — ``/api/v1/email-templates``.

Gives an organization control of the mail the product sends on its behalf:

  * ``GET  /catalog``            every customisable message, its merge fields
                                 and whether the org has overridden it
  * ``GET  /{key}``              the editable copy (override, or the default)
  * ``PUT  /{key}``              save an override
  * ``DELETE /{key}``            revert to the built-in copy
  * ``POST /{key}/preview``      render with sample or supplied values
  * ``POST /{key}/test``         send the rendered message to one address
  * ``GET|PUT /branding``        the wrapper applied to every message

Preview is deliberately a first-class endpoint: the fastest way to lose trust in
a mail editor is to make someone send a real message to find out what it looks
like.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.email_branding import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_HEADER_COLOR,
    EmailBranding,
    EmailTemplate,
)
from app.models.user import User
from app.services import email_catalog, email_template_service
from app.services.activity_service import log_activity
from app.utils.email_client import EmailCategory, send_email

router = APIRouter()

Admin = require_role("admin")
Viewer = require_role("admin", "editor", "accountant", "viewer")


# ─── Schemas ────────────────────────────────────────────────────────────────

class MergeFieldOut(BaseModel):
    name: str
    label: str
    sample: str


class CatalogEntry(BaseModel):
    key: str
    label: str
    category: str
    description: str
    is_customized: bool
    is_active: bool
    updated_at: datetime | None = None


class TemplateDetail(BaseModel):
    key: str
    label: str
    category: str
    description: str
    subject: str
    body: str
    default_subject: str
    default_body: str
    is_customized: bool
    is_active: bool
    merge_fields: list[MergeFieldOut]


class TemplateSave(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    is_active: bool = True


class PreviewRequest(BaseModel):
    """Preview unsaved edits; omitted fields fall back to what is stored."""

    subject: str | None = None
    body: str | None = None
    context: dict[str, str] | None = None


class PreviewResponse(BaseModel):
    subject: str
    html_body: str
    is_customized: bool
    unknown_fields: list[str]


class TestSendRequest(BaseModel):
    to: EmailStr
    subject: str | None = None
    body: str | None = None


class BrandingOut(BaseModel):
    sender_name: str | None
    reply_to: str | None
    logo_url: str | None
    header_color: str
    accent_color: str
    signature: str | None
    footer_text: str | None
    postal_address: str | None
    is_active: bool
    is_configured: bool


class BrandingSave(BaseModel):
    sender_name: str | None = Field(default=None, max_length=120)
    reply_to: EmailStr | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    header_color: str = Field(default=DEFAULT_HEADER_COLOR, max_length=9)
    accent_color: str = Field(default=DEFAULT_ACCENT_COLOR, max_length=9)
    signature: str | None = None
    footer_text: str | None = None
    postal_address: str | None = None
    is_active: bool = True


# ─── Helpers ────────────────────────────────────────────────────────────────

def _definition_or_404(key: str):
    definition = email_catalog.get(key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown email template: {key}"
        )
    return definition


def _branding_out(branding: EmailBranding | None) -> BrandingOut:
    if branding is None:
        return BrandingOut(
            sender_name=None,
            reply_to=None,
            logo_url=None,
            header_color=DEFAULT_HEADER_COLOR,
            accent_color=DEFAULT_ACCENT_COLOR,
            signature=None,
            footer_text=None,
            postal_address=None,
            is_active=True,
            is_configured=False,
        )
    return BrandingOut(
        sender_name=branding.sender_name,
        reply_to=branding.reply_to,
        logo_url=branding.logo_url,
        header_color=branding.header_color,
        accent_color=branding.accent_color,
        signature=branding.signature,
        footer_text=branding.footer_text,
        postal_address=branding.postal_address,
        is_active=branding.is_active,
        is_configured=True,
    )


# ─── Catalog ────────────────────────────────────────────────────────────────

@router.get("/catalog", response_model=list[CatalogEntry])
async def list_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Viewer),
):
    """Every customisable message, marked with whether this org has changed it."""
    overrides = {
        row.template_key: row
        for row in (
            await db.execute(
                select(EmailTemplate).where(
                    EmailTemplate.organization_id == current_user.organization_id
                )
            )
        )
        .scalars()
        .all()
    }
    return [
        CatalogEntry(
            key=definition.key,
            label=definition.label,
            category=definition.category,
            description=definition.description,
            is_customized=definition.key in overrides,
            is_active=overrides[definition.key].is_active
            if definition.key in overrides
            else True,
            updated_at=overrides[definition.key].updated_at
            if definition.key in overrides
            else None,
        )
        for definition in email_catalog.TEMPLATE_CATALOG.values()
    ]


@router.get("/branding", response_model=BrandingOut)
async def get_branding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Viewer),
):
    branding = await email_template_service.get_branding(
        db, current_user.organization_id
    )
    return _branding_out(branding)


@router.put("/branding", response_model=BrandingOut)
async def save_branding(
    payload: BrandingSave,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    """Save the wrapper applied to every message this organization sends."""
    org_id = current_user.organization_id
    branding = (
        await db.execute(
            select(EmailBranding).where(EmailBranding.organization_id == org_id)
        )
    ).scalar_one_or_none()

    if branding is None:
        branding = EmailBranding(organization_id=org_id)
        db.add(branding)

    data = payload.model_dump()
    if data.get("reply_to") is not None:
        data["reply_to"] = str(data["reply_to"])
    for field_name, value in data.items():
        setattr(branding, field_name, value)

    await db.commit()
    await db.refresh(branding)
    await log_activity(
        db,
        user=current_user,
        action="update",
        entity_type="email_branding",
        entity_id=branding.id,
        entity_label="Email branding",
    )
    return _branding_out(branding)


# ─── Single template ────────────────────────────────────────────────────────

@router.get("/{template_key}", response_model=TemplateDetail)
async def get_template(
    template_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Viewer),
):
    definition = _definition_or_404(template_key)
    override = await email_template_service.get_override(
        db, current_user.organization_id, template_key
    )
    return TemplateDetail(
        key=definition.key,
        label=definition.label,
        category=definition.category,
        description=definition.description,
        subject=(override.subject_template if override else None)
        or definition.default_subject,
        body=(override.body_template if override else None) or definition.default_body,
        default_subject=definition.default_subject,
        default_body=definition.default_body,
        is_customized=override is not None,
        is_active=override.is_active if override else True,
        merge_fields=[
            MergeFieldOut(name=f.name, label=f.label, sample=f.sample)
            for f in definition.merge_fields
        ],
    )


@router.put("/{template_key}", response_model=TemplateDetail)
async def save_template(
    template_key: str,
    payload: TemplateSave,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    definition = _definition_or_404(template_key)
    org_id = current_user.organization_id

    override = await email_template_service.get_override(db, org_id, template_key)
    if override is None:
        override = EmailTemplate(organization_id=org_id, template_key=template_key)
        db.add(override)

    override.subject_template = payload.subject
    override.body_template = payload.body
    override.is_active = payload.is_active
    override.updated_by_id = current_user.id

    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="update",
        entity_type="email_template",
        entity_id=override.id,
        entity_label=definition.label,
    )
    return await get_template(template_key, db, current_user)


@router.delete("/{template_key}", response_model=TemplateDetail)
async def reset_template(
    template_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    """Discard the override and go back to the copy the product ships with."""
    definition = _definition_or_404(template_key)
    override = await email_template_service.get_override(
        db, current_user.organization_id, template_key
    )
    if override is not None:
        await db.delete(override)
        await db.commit()
        await log_activity(
            db,
            user=current_user,
            action="delete",
            entity_type="email_template",
            entity_id=override.id,
            entity_label=definition.label,
        )
    return await get_template(template_key, db, current_user)


@router.post("/{template_key}/preview", response_model=PreviewResponse)
async def preview_template(
    template_key: str,
    payload: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Viewer),
):
    """Render the message exactly as a recipient would see it."""
    definition = _definition_or_404(template_key)
    org_id = current_user.organization_id

    override = await email_template_service.get_override(db, org_id, template_key)
    subject_source = (
        payload.subject
        if payload.subject is not None
        else (override.subject_template if override else None)
        or definition.default_subject
    )
    body_source = (
        payload.body
        if payload.body is not None
        else (override.body_template if override else None) or definition.default_body
    )

    context = {
        **email_catalog.sample_context(template_key),
        **(payload.context or {}),
    }
    context["organization_name"] = await email_template_service.organization_name(
        db, org_id
    )

    branding = await email_template_service.get_branding(db, org_id)
    subject = email_template_service.substitute(subject_source, context)
    body = email_template_service.wrap(
        email_template_service.substitute(body_source, context),
        branding=branding,
        org_name=context["organization_name"],
        preheader=subject,
    )

    return PreviewResponse(
        subject=subject,
        html_body=body,
        is_customized=override is not None,
        unknown_fields=email_template_service.unknown_fields(
            f"{subject_source}\n{body_source}", template_key
        ),
    )


@router.post("/{template_key}/test")
async def test_send(
    template_key: str,
    payload: TestSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    """Send the rendered message to one address so it can be checked for real."""
    _definition_or_404(template_key)
    preview = await preview_template(
        template_key,
        PreviewRequest(subject=payload.subject, body=payload.body),
        db,
        current_user,
    )
    sender_name, reply_to = await email_template_service.sender_identity(
        db, current_user.organization_id
    )
    sent = await send_email(
        str(payload.to),
        f"[Test] {preview.subject}",
        preview.html_body,
        category=EmailCategory.NOTIFICATIONS,
        sender_name=sender_name,
        reply_to=reply_to,
    )

    override = await email_template_service.get_override(
        db, current_user.organization_id, template_key
    )
    if override is not None:
        override.last_tested_at = datetime.now(timezone.utc)
        await db.commit()

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The message could not be sent. Check that outbound email is "
                "configured (SMTP_HOST) and try again."
            ),
        )
    return {"sent": True, "to": str(payload.to)}

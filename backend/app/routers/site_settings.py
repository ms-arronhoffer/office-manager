import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.schemas.site_settings import (
    SiteSettingsSchema,
    DEFAULT_COMPANY_NAME,
    DEFAULT_COMPANY_ADDRESS,
    DEFAULT_COMPANY_PHONE,
    DEFAULT_COMPANY_EMAIL,
    DEFAULT_LOGIN_SUBTITLE,
    DEFAULT_LOGIN_FORM_HEADER,
    DEFAULT_LOGIN_FORM_DESCRIPTION,
    DEFAULT_SLA_HIGH_DAYS,
    DEFAULT_SLA_MEDIUM_DAYS,
    DEFAULT_SLA_LOW_DAYS,
)

router = APIRouter()


async def _get_or_create(db: AsyncSession, organization_id: uuid.UUID) -> SiteSettings:
    res = await db.execute(
        select(SiteSettings).where(SiteSettings.organization_id == organization_id)
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = SiteSettings(
            organization_id=organization_id,
            company_name=DEFAULT_COMPANY_NAME,
            company_address=DEFAULT_COMPANY_ADDRESS,
            company_phone=DEFAULT_COMPANY_PHONE,
            company_email=DEFAULT_COMPANY_EMAIL,
            login_subtitle=DEFAULT_LOGIN_SUBTITLE,
            login_form_header=DEFAULT_LOGIN_FORM_HEADER,
            login_form_description=DEFAULT_LOGIN_FORM_DESCRIPTION,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("", response_model=SiteSettingsSchema)
async def get_site_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    row = await _get_or_create(db, current_user.organization_id)
    return SiteSettingsSchema(
        company_name=row.company_name or DEFAULT_COMPANY_NAME,
        company_address=row.company_address or DEFAULT_COMPANY_ADDRESS,
        company_phone=row.company_phone or DEFAULT_COMPANY_PHONE,
        company_email=row.company_email or DEFAULT_COMPANY_EMAIL,
        login_subtitle=row.login_subtitle or DEFAULT_LOGIN_SUBTITLE,
        login_form_header=row.login_form_header or DEFAULT_LOGIN_FORM_HEADER,
        login_form_description=row.login_form_description or DEFAULT_LOGIN_FORM_DESCRIPTION,
        sla_high_days=row.sla_high_days if row.sla_high_days is not None else DEFAULT_SLA_HIGH_DAYS,
        sla_medium_days=row.sla_medium_days if row.sla_medium_days is not None else DEFAULT_SLA_MEDIUM_DAYS,
        sla_low_days=row.sla_low_days if row.sla_low_days is not None else DEFAULT_SLA_LOW_DAYS,
    )


@router.put("", response_model=SiteSettingsSchema)
async def update_site_settings(
    payload: SiteSettingsSchema,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    row = await _get_or_create(db, current_user.organization_id)
    row.company_name = payload.company_name
    row.company_address = payload.company_address
    row.company_phone = payload.company_phone
    row.company_email = payload.company_email
    row.login_subtitle = payload.login_subtitle
    row.login_form_header = payload.login_form_header
    row.login_form_description = payload.login_form_description
    row.sla_high_days = payload.sla_high_days
    row.sla_medium_days = payload.sla_medium_days
    row.sla_low_days = payload.sla_low_days
    await db.commit()
    await db.refresh(row)
    return payload


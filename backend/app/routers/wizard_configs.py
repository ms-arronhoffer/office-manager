import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.models.wizard_config import WizardConfig
from app.schemas.wizard_config import (
    WizardConfigCreate,
    WizardConfigResponse,
    WizardConfigUpdate,
)

router = APIRouter()


@router.get("/active", response_model=WizardConfigResponse)
async def get_active_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the active default wizard config. Any authenticated user can access this."""
    result = await db.execute(
        select(WizardConfig).where(
            WizardConfig.is_active.is_(True),
            WizardConfig.is_default.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active wizard configuration found.",
        )
    return WizardConfigResponse.model_validate(config, from_attributes=True)


@router.get("", response_model=list[WizardConfigResponse])
async def list_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(WizardConfig).order_by(WizardConfig.created_at.desc())
    )
    return [
        WizardConfigResponse.model_validate(c, from_attributes=True)
        for c in result.scalars().all()
    ]


@router.get("/{config_id}", response_model=WizardConfigResponse)
async def get_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(WizardConfig).where(WizardConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    return WizardConfigResponse.model_validate(config, from_attributes=True)


@router.post("", response_model=WizardConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_config(
    payload: WizardConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.is_default:
        await db.execute(
            update(WizardConfig).values(is_default=False)
        )
    config = WizardConfig(
        name=payload.name,
        description=payload.description,
        steps=payload.steps,
        is_active=payload.is_active,
        is_default=payload.is_default,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return WizardConfigResponse.model_validate(config, from_attributes=True)


@router.put("/{config_id}", response_model=WizardConfigResponse)
async def update_config(
    config_id: uuid.UUID,
    payload: WizardConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(WizardConfig).where(WizardConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("is_default"):
        await db.execute(
            update(WizardConfig)
            .where(WizardConfig.id != config_id)
            .values(is_default=False)
        )

    for key, value in update_data.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)
    return WizardConfigResponse.model_validate(config, from_attributes=True)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(WizardConfig).where(WizardConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    await db.delete(config)
    await db.commit()

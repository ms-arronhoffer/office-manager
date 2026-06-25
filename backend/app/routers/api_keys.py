import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.api_key import ApiKey, generate_api_key
from app.models.user import User

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = ["read:all"]
    expires_in_days: int | None = None


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    is_active: bool | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("scopes", mode="before")
    @classmethod
    def parse_scopes(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


class ApiKeyCreated(ApiKeyResponse):
    key: str  # Full key — returned exactly once, never stored


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.organization_id == current_user.organization_id,
        ).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    full_key, prefix, key_hash = generate_api_key()
    expires_at = None
    if payload.expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)

    api_key = ApiKey(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=",".join(payload.scopes),
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreated.model_construct(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scopes=api_key.scopes.split(",") if api_key.scopes else [],
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        key=full_key,
    )


@router.patch("/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: uuid.UUID,
    payload: ApiKeyUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.organization_id == current_user.organization_id,
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    if payload.name is not None:
        api_key.name = payload.name
    if payload.scopes is not None:
        api_key.scopes = ",".join(payload.scopes)
    if payload.is_active is not None:
        api_key.is_active = payload.is_active

    await db.commit()
    await db.refresh(api_key)
    return api_key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.organization_id == current_user.organization_id,
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await db.delete(api_key)
    await db.commit()

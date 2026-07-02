import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery
from app.services.webhook_service import dispatch_webhook

router = APIRouter()


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class WebhookCreate(BaseModel):
    url: str
    events: str = "*"

    @field_validator("url")
    @classmethod
    def url_must_be_https(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class WebhookUpdate(BaseModel):
    url: str | None = None
    events: str | None = None
    is_active: bool | None = None


class WebhookResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    url: str
    events: str
    is_active: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: uuid.UUID
    webhook_id: uuid.UUID
    event_type: str
    payload_snapshot: str | None
    status: str
    response_code: int | None
    response_body: str | None
    attempt_count: int
    next_retry_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Webhook)
        .where(Webhook.organization_id == current_user.organization_id)
        .order_by(Webhook.created_at.desc())
    )
    return [WebhookResponse.model_validate(w) for w in result.scalars().all()]


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    webhook = Webhook(
        organization_id=current_user.organization_id,
        url=payload.url,
        events=payload.events,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.organization_id == current_user.organization_id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(webhook, field, value)

    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.organization_id == current_user.organization_id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await db.delete(webhook)
    await db.commit()


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryResponse)
async def test_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Send a test ping payload to the webhook URL."""
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.organization_id == current_user.organization_id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")

    # Dispatch a synthetic test event
    await dispatch_webhook(
        db,
        org_id=current_user.organization_id,
        event_type="test.ping",
        payload={"message": "This is a test delivery from Portfolio Desk.", "webhook_id": str(webhook_id)},
    )

    # Return the latest delivery record for this webhook
    delivery_result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(1)
    )
    delivery = delivery_result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Delivery record not found after test")
    return WebhookDeliveryResponse.model_validate(delivery)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse])
async def list_deliveries(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    # Verify ownership
    wh_result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.organization_id == current_user.organization_id,
        )
    )
    if not wh_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")

    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(100)
    )
    return [WebhookDeliveryResponse.model_validate(d) for d in result.scalars().all()]

"""Tenant-specific Stripe webhooks for resident ACH settlement and returns."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.customer_invoice import CustomerReceipt
from app.models.organization_integration_config import OrganizationIntegrationConfig
from app.models.resident_payment_attempt import (
    ResidentPaymentAttempt,
    ResidentPaymentWebhookEvent,
)
from app.services import ar_service, resident_ach_service
from app.services.resident_ach_service import verify_stripe_signature
from app.utils.crypto import decrypt_secret
from app.utils.rls import set_session_org, set_system_bypass

router = APIRouter()

_RETURN_EVENTS = {"charge.refunded", "charge.dispute.created"}
_SUPPORTED_EVENTS = {"charge.succeeded", "charge.failed", *_RETURN_EVENTS}


async def _tenant_config(
    db: AsyncSession, webhook_key: str
) -> OrganizationIntegrationConfig:
    await set_system_bypass(db)
    row = (
        await db.execute(
            select(OrganizationIntegrationConfig).where(
                OrganizationIntegrationConfig.provider == "resident_payments",
                OrganizationIntegrationConfig.webhook_key == webhook_key,
                OrganizationIntegrationConfig.is_enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.webhook_secret_encrypted:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found.")
    await set_session_org(db, row.organization_id)
    return row


async def _fail_or_return_attempt(
    db: AsyncSession,
    attempt: ResidentPaymentAttempt,
    *,
    event_type: str,
    failure_code: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    if event_type == "charge.refunded" and failure_code == "partial_refund":
        attempt.failure_code = failure_code
        attempt.failure_detail = (
            "Stripe reported a partial refund. Automatic full receipt reversal was skipped; "
            "review and post the partial accounting adjustment manually."
        )
        return
    if attempt.status == "succeeded" or event_type in _RETURN_EVENTS:
        receipts = (
            await db.execute(
                select(CustomerReceipt).where(
                    CustomerReceipt.organization_id == attempt.organization_id,
                    CustomerReceipt.reference == attempt.processor_ref,
                )
            )
        ).scalars().all()
        for receipt in receipts:
            await ar_service.reverse_receipt_in_gl(
                db, attempt.organization_id, receipt, commit=False
            )
        attempt.status = "returned"
        attempt.return_code = failure_code or event_type
        attempt.returned_at = now
    elif attempt.status == "processing":
        attempt.status = "failed"
        attempt.failure_code = failure_code
        attempt.failed_at = now


@router.post("/resident-payments/stripe/webhook/{webhook_key}", status_code=204)
async def resident_stripe_webhook(
    webhook_key: str,
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    row = await _tenant_config(db, webhook_key)
    body = await request.body()
    secret = decrypt_secret(row.webhook_secret_encrypted)
    if not stripe_signature or not verify_stripe_signature(body, stripe_signature, secret):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    try:
        event = json.loads(body)
        event_id = str(event["id"])
        event_type = str(event["type"])
        charge = event["data"]["object"]
        processor_ref = str(charge["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe event.") from exc

    if event_type not in _SUPPORTED_EVENTS:
        return None
    replay = (
        await db.execute(
            select(ResidentPaymentWebhookEvent).where(
                ResidentPaymentWebhookEvent.organization_id == row.organization_id,
                ResidentPaymentWebhookEvent.stripe_event_id == event_id,
            )
        )
    ).scalar_one_or_none()
    if replay is not None:
        return None

    attempt = (
        await db.execute(
            select(ResidentPaymentAttempt)
            .where(
                ResidentPaymentAttempt.organization_id == row.organization_id,
                ResidentPaymentAttempt.processor_ref == processor_ref,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if attempt is None:
        attempt_id = (charge.get("metadata") or {}).get("resident_payment_attempt_id")
        if attempt_id:
            attempt = (
                await db.execute(
                    select(ResidentPaymentAttempt)
                    .where(
                        ResidentPaymentAttempt.id == attempt_id,
                        ResidentPaymentAttempt.organization_id == row.organization_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
    if attempt is not None and not attempt.processor_ref:
        attempt.processor_ref = processor_ref
    db.add(
        ResidentPaymentWebhookEvent(
            organization_id=row.organization_id,
            stripe_event_id=event_id,
            event_type=event_type,
            processor_ref=processor_ref,
        )
    )
    if attempt is not None:
        if event_type == "charge.succeeded":
            await resident_ach_service.settle_attempt(db, attempt)
        else:
            failure_code = charge.get("failure_code") or (charge.get("outcome") or {}).get("reason")
            if event_type == "charge.refunded" and not charge.get("refunded"):
                failure_code = "partial_refund"
            await _fail_or_return_attempt(
                db, attempt, event_type=event_type, failure_code=failure_code
            )
    await db.commit()
    return None

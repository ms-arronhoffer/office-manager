"""
Webhook dispatch service.

Sends signed HTTP POST requests to registered webhook endpoints whenever
an event occurs.  Delivery results are recorded in ``webhook_deliveries``.

Signing: HMAC-SHA256 over the raw JSON body, hex-encoded, sent as
``X-Signature: sha256=<hex>`` so receivers can verify authenticity.

Retry policy: failed deliveries are retried up to 3 times total with
exponential backoff (1 min, 5 min, 30 min) via the background scheduler.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import Webhook, WebhookDelivery

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
# Seconds to wait before each retry attempt (indexed by attempt_count after failure)
_RETRY_DELAYS = [60, 300, 1800]  # 1 min, 5 min, 30 min
MAX_ATTEMPTS = 3


def _sign_payload(secret: str, body: bytes) -> str:
    """Return ``sha256=<hex>`` signature string."""
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _webhook_matches(webhook: Webhook, event_type: str) -> bool:
    """Return True if the webhook is subscribed to *event_type*."""
    if not webhook.is_active:
        return False
    events = webhook.events or "*"
    if events.strip() == "*":
        return True
    subscribed = {e.strip() for e in events.split(",")}
    return event_type in subscribed


async def dispatch_webhook(
    db: AsyncSession,
    org_id: uuid.UUID | None,
    event_type: str,
    payload: dict,
) -> None:
    """
    Fan out *payload* to all active webhooks for *org_id* that match
    *event_type*.  Each delivery attempt is logged; failed deliveries are
    scheduled for automatic retry via the background scheduler.
    """
    if org_id is None:
        return

    result = await db.execute(
        select(Webhook).where(
            Webhook.organization_id == org_id,
            Webhook.is_active.is_(True),
        )
    )
    webhooks = result.scalars().all()
    if not webhooks:
        return

    body = json.dumps({"event": event_type, "data": payload}, default=str).encode()
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for webhook in webhooks:
            if not _webhook_matches(webhook, event_type):
                continue

            signature = _sign_payload(webhook.secret, body)
            delivery = WebhookDelivery(
                id=uuid.uuid4(),
                webhook_id=webhook.id,
                event_type=event_type,
                payload_snapshot=body.decode(),
                status="pending",
                attempt_count=1,
                created_at=now,
            )
            db.add(delivery)

            try:
                resp = await client.post(
                    webhook.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature": signature,
                        "X-Event-Type": event_type,
                    },
                )
                if resp.is_success:
                    delivery.status = "success"
                    delivery.next_retry_at = None
                else:
                    delivery.status = "failed"
                    delivery.next_retry_at = now + timedelta(seconds=_RETRY_DELAYS[0])
                delivery.response_code = resp.status_code
                delivery.response_body = resp.text[:2000]
            except Exception as exc:
                log.warning("Webhook delivery failed for %s → %s: %s", event_type, webhook.url, exc)
                delivery.status = "failed"
                delivery.response_body = str(exc)[:2000]
                delivery.next_retry_at = now + timedelta(seconds=_RETRY_DELAYS[0])

            webhook.last_triggered_at = now

    try:
        await db.commit()
    except Exception as exc:
        log.warning("Failed to persist webhook delivery records: %s", exc)
        await db.rollback()

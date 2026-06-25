"""APScheduler task: retry failed webhook deliveries with exponential backoff."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.database import async_session
from app.models.webhook import Webhook, WebhookDelivery
from app.services.webhook_service import _sign_payload, _TIMEOUT, _RETRY_DELAYS, MAX_ATTEMPTS

log = logging.getLogger(__name__)


async def retry_failed_webhooks() -> None:
    """
    Runs every 2 minutes via APScheduler.

    Picks up WebhookDelivery rows where:
      - status == 'failed'
      - next_retry_at is not None and <= now
      - attempt_count < MAX_ATTEMPTS

    Retries each delivery with HMAC signing.  On success sets status='success'.
    On continued failure increments attempt_count and schedules the next retry
    using exponential backoff; clears next_retry_at after the final attempt.
    """
    async with async_session() as db:
        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.status == "failed",
                WebhookDelivery.next_retry_at.is_not(None),
                WebhookDelivery.next_retry_at <= now,
                WebhookDelivery.attempt_count < MAX_ATTEMPTS,
            )
        )
        deliveries = result.scalars().all()

        if not deliveries:
            return

        log.info("Retrying %d failed webhook deliveries", len(deliveries))

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for delivery in deliveries:
                # Load the parent webhook — skip if deleted or deactivated
                wh_result = await db.execute(
                    select(Webhook).where(
                        Webhook.id == delivery.webhook_id,
                        Webhook.is_active.is_(True),
                    )
                )
                webhook = wh_result.scalar_one_or_none()
                if not webhook:
                    delivery.next_retry_at = None  # parent gone, stop retrying
                    continue

                body = (delivery.payload_snapshot or "{}").encode()
                signature = _sign_payload(webhook.secret, body)
                delivery.attempt_count += 1

                try:
                    resp = await client.post(
                        webhook.url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Signature": signature,
                            "X-Event-Type": delivery.event_type,
                        },
                    )
                    delivery.response_code = resp.status_code
                    delivery.response_body = resp.text[:2000]
                    if resp.is_success:
                        delivery.status = "success"
                        delivery.next_retry_at = None
                        webhook.last_triggered_at = now
                    else:
                        _schedule_next_retry(delivery, now)
                except Exception as exc:
                    log.warning(
                        "Webhook retry failed for delivery %s (attempt %d): %s",
                        delivery.id, delivery.attempt_count, exc,
                    )
                    delivery.response_body = str(exc)[:2000]
                    _schedule_next_retry(delivery, now)

        try:
            await db.commit()
        except Exception:
            log.exception("Failed to persist webhook retry results")
            await db.rollback()


def _schedule_next_retry(delivery: WebhookDelivery, now: datetime) -> None:
    """Set next_retry_at using exponential backoff, or clear it after max attempts."""
    if delivery.attempt_count >= MAX_ATTEMPTS:
        delivery.next_retry_at = None  # exhausted — no more retries
        return
    # attempt_count is now 2 or 3 after increment; use index attempt_count-1 for delay
    delay_idx = min(delivery.attempt_count - 1, len(_RETRY_DELAYS) - 1)
    delivery.next_retry_at = now + timedelta(seconds=_RETRY_DELAYS[delay_idx])

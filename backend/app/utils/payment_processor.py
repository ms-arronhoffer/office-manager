"""Payment processor client for inbound money (Phase 2.3).

A thin, provider-agnostic gateway for charging a resident's card or bank account
(ACH). It mirrors :mod:`app.utils.sms_client` and :mod:`app.utils.email_client`:
when no processor is configured it degrades gracefully to a logged no-op that
reports the charge as *not captured*, so the rest of the app can record the
payment intent without a live processor in dev/test.

The default implementation targets a Stripe-style HTTP API and only activates
when ``PAYMENTS_API_KEY`` is set. Real integrations would exchange a tokenised
payment method (never raw PAN/bank numbers) for a charge; this module accepts an
opaque ``payment_token`` and never stores card/bank data.
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.config import settings
from app.services.organization_integration_settings import (
    ResidentPaymentsSettings,
    legacy_settings,
)

logger = logging.getLogger(__name__)

# Inbound payment methods this gateway understands.
PAYMENT_METHODS = ("card", "ach")


@dataclass
class ChargeResult:
    """Outcome of a charge attempt."""

    captured: bool
    status: str  # "succeeded" | "processing" | "unconfigured" | "failed"
    processor_ref: str | None = None
    detail: str | None = None


def _configured(config: ResidentPaymentsSettings) -> bool:
    return bool(config.is_enabled and config.secret_api_key)


def _error_detail(resp: httpx.Response) -> str:
    """Extract a human-readable message from a Stripe error body."""
    try:
        err = resp.json().get("error") or {}
        message = err.get("message")
        if message:
            return str(message)
    except Exception:  # pragma: no cover - non-JSON error body
        pass
    return f"Processor HTTP {resp.status_code}."


async def charge_payment(
    amount: Decimal,
    *,
    method: str,
    payment_token: str | None = None,
    stripe_customer_id: str | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, str] | None = None,
    config: ResidentPaymentsSettings | None = None,
) -> ChargeResult:
    """Attempt to capture ``amount`` from a tokenised payment method.

    Returns a :class:`ChargeResult`. When the processor is not configured (the
    common dev/test case) the charge is reported as ``unconfigured`` and *not*
    captured, so callers can still record a pending/offline receipt without a
    live gateway. Never accepts or stores raw card/bank numbers — only an opaque
    ``payment_token`` produced client-side by the processor.

    ``idempotency_key`` is sent to the processor so a retried request (network
    timeout, user double-click) settles onto the same charge instead of taking
    the money twice. One is generated when the caller does not supply one.
    """
    if method not in PAYMENT_METHODS:
        return ChargeResult(False, "failed", detail=f"Unsupported method '{method}'.")
    if amount is None or Decimal(str(amount)) <= 0:
        return ChargeResult(False, "failed", detail="Charge amount must be positive.")

    config = config or legacy_settings("resident_payments")
    if not _configured(config):
        logger.info(
            "Payment skipped (processor not configured): amount=%s method=%s",
            amount, method,
        )
        return ChargeResult(False, "unconfigured", detail="Payment processor not configured.")

    if not payment_token:
        return ChargeResult(False, "failed", detail="A payment_token is required to capture funds.")

    provider = config.provider
    url = config.api_url or "https://api.stripe.com/v1/payment_intents"
    # Amounts are sent in the smallest currency unit (cents).
    cents = int((Decimal(str(amount)) * 100).to_integral_value())
    if method == "ach":
        if not payment_token.startswith("ba_") or not (stripe_customer_id or "").startswith("cus_"):
            return ChargeResult(
                False, "failed", detail="ACH requires a saved Stripe customer bank source."
            )
        from urllib.parse import urlparse

        parsed = urlparse(url)
        url = f"{parsed.scheme}://{parsed.netloc}/v1/charges"
        data = {
            "amount": cents,
            "currency": "usd",
            "customer": stripe_customer_id,
            "source": payment_token,
            "description": description or "",
        }
    else:
        data = {
            "amount": cents,
            "currency": "usd",
            "payment_method": payment_token,
            "payment_method_types[]": "card",
            "confirm": "true",
            "off_session": "true",
            "description": description or "",
        }
    for key, value in (metadata or {}).items():
        data[f"metadata[{key}]"] = value
    headers = {
        "Authorization": "Bearer " + config.secret_api_key,
        "Idempotency-Key": idempotency_key or str(uuid.uuid4()),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(url, data=data, headers=headers)
        if resp.status_code >= 400:
            detail = _error_detail(resp)
            logger.warning(
                "Payment declined via %s: HTTP %s (%s)", provider, resp.status_code, detail
            )
            return ChargeResult(False, "failed", detail=detail)
        body = {}
        try:
            body = resp.json()
        except Exception:  # pragma: no cover - non-JSON body
            body = {}
        ref = body.get("id")
        processor_status = body.get("status")
        if method == "ach" and processor_status == "pending":
            return ChargeResult(False, "processing", processor_ref=ref)
        if processor_status not in (None, "succeeded"):
            return ChargeResult(
                False,
                "failed",
                processor_ref=ref,
                detail=f"Payment not captured (processor status '{processor_status}').",
            )
        return ChargeResult(True, "succeeded", processor_ref=ref or str(uuid.uuid4()))
    except Exception as e:  # pragma: no cover - network failure path
        logger.warning("Payment error via %s: %s", provider, e)
        return ChargeResult(False, "failed", detail=str(e))

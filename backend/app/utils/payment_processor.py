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

logger = logging.getLogger(__name__)

# Inbound payment methods this gateway understands.
PAYMENT_METHODS = ("card", "ach")


@dataclass
class ChargeResult:
    """Outcome of a charge attempt."""

    captured: bool
    status: str  # "captured" | "unconfigured" | "failed"
    processor_ref: str | None = None
    detail: str | None = None


def _configured() -> bool:
    return bool(getattr(settings, "PAYMENTS_API_KEY", None))


async def charge_payment(
    amount: Decimal,
    *,
    method: str,
    payment_token: str | None = None,
    description: str | None = None,
) -> ChargeResult:
    """Attempt to capture ``amount`` from a tokenised payment method.

    Returns a :class:`ChargeResult`. When the processor is not configured (the
    common dev/test case) the charge is reported as ``unconfigured`` and *not*
    captured, so callers can still record a pending/offline receipt without a
    live gateway. Never accepts or stores raw card/bank numbers — only an opaque
    ``payment_token`` produced client-side by the processor.
    """
    if method not in PAYMENT_METHODS:
        return ChargeResult(False, "failed", detail=f"Unsupported method '{method}'.")
    if amount is None or Decimal(str(amount)) <= 0:
        return ChargeResult(False, "failed", detail="Charge amount must be positive.")

    if not _configured():
        logger.info(
            "Payment skipped (processor not configured): amount=%s method=%s",
            amount, method,
        )
        return ChargeResult(False, "unconfigured", detail="Payment processor not configured.")

    if not payment_token:
        return ChargeResult(False, "failed", detail="A payment_token is required to capture funds.")

    provider = getattr(settings, "PAYMENTS_PROVIDER", "stripe") or "stripe"
    url = getattr(settings, "PAYMENTS_API_URL", "") or "https://api.stripe.com/v1/charges"
    # Amounts are sent in the smallest currency unit (cents).
    cents = int((Decimal(str(amount)) * 100).to_integral_value())
    data = {
        "amount": cents,
        "currency": "usd",
        "source": payment_token,
        "description": description or "",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                url,
                data=data,
                headers={"Authorization": "Bearer " + str(settings.PAYMENTS_API_KEY)},
            )
        if resp.status_code >= 400:
            logger.warning("Payment failed via %s: HTTP %s", provider, resp.status_code)
            return ChargeResult(False, "failed", detail=f"Processor HTTP {resp.status_code}.")
        ref = None
        try:
            ref = resp.json().get("id")
        except Exception:  # pragma: no cover - non-JSON body
            ref = None
        return ChargeResult(True, "captured", processor_ref=ref or str(uuid.uuid4()))
    except Exception as e:  # pragma: no cover - network failure path
        logger.warning("Payment error via %s: %s", provider, e)
        return ChargeResult(False, "failed", detail=str(e))

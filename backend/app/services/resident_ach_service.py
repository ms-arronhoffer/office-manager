"""Plaid Auth to Stripe bank source orchestration for resident payments.

Plaid returns a short-lived ``btok_`` bank token. Stripe attaches that token to
one tenant-specific Customer and returns a reusable ``ba_`` bank source. The
application stores only the Customer/source identifiers and display metadata.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.customer_invoice import CustomerInvoice
from app.models.resident_payment_attempt import ResidentPaymentAttempt
from app.services import rent_service
from app.services.bank_feed.plaid_client import PlaidClient
from app.services.organization_integration_settings import PlaidSettings, ResidentPaymentsSettings


ACH_CONSENT_VERSION = "resident-ach-link-v1"
ACH_CONSENT_TEXT = (
    "I authorize this property manager and its payment processor to link the selected "
    "bank account for resident payments. Saving an account does not initiate a debit."
)
AUTOPAY_CONSENT_VERSION = "resident-ach-autopay-v1"
AUTOPAY_CONSENT_TEXT = (
    "I authorize recurring ACH debits for amounts due under my lease using the selected "
    "bank account until I disable autopay or revoke this authorization."
)


async def settle_attempt(db: AsyncSession, attempt: ResidentPaymentAttempt) -> None:
    """Post a settled ACH attempt to AR and GL exactly once."""
    if attempt.status == "succeeded":
        return
    first_receipt_id = None
    for allocation in attempt.allocation_json:
        invoice = (
            await db.execute(
                select(CustomerInvoice)
                .where(
                    CustomerInvoice.id == allocation["invoice_id"],
                    CustomerInvoice.organization_id == attempt.organization_id,
                )
                .options(selectinload(CustomerInvoice.receipts))
            )
        ).scalar_one_or_none()
        if invoice is None:
            continue
        result = await rent_service.record_settled_resident_payment(
            db,
            attempt.organization_id,
            invoice,
            allocation["amount"],
            method="ach",
            processor_ref=attempt.processor_ref or "",
        )
        first_receipt_id = first_receipt_id or result["receipt"].id
    attempt.receipt_id = first_receipt_id
    attempt.status = "succeeded"
    attempt.settled_at = datetime.now(timezone.utc)


class ResidentAchError(ValueError):
    """A resident-safe ACH setup or processor error."""


@dataclass(frozen=True)
class AchCapability:
    available: bool
    reason: str | None


def ach_capability(
    plaid: PlaidSettings, payments: ResidentPaymentsSettings
) -> AchCapability:
    if not plaid.is_enabled or not plaid.resident_ach_enabled:
        return AchCapability(False, "Bank payments are not enabled for this property.")
    if not plaid.client_id or not plaid.secret:
        return AchCapability(False, "Bank-link configuration is incomplete.")
    if not payments.is_enabled or payments.provider.lower() != "stripe":
        return AchCapability(False, "Resident Stripe payments are not enabled.")
    if not payments.secret_api_key:
        return AchCapability(False, "Resident Stripe configuration is incomplete.")
    plaid_live = plaid.environment == "production"
    stripe_live = payments.secret_api_key.startswith("sk_live_")
    if plaid_live != stripe_live:
        return AchCapability(False, "Plaid and Stripe modes do not match.")
    return AchCapability(True, None)


def _stripe_origin(config: ResidentPaymentsSettings) -> str:
    parsed = urlparse(config.api_url or "https://api.stripe.com/v1/payment_intents")
    return f"{parsed.scheme}://{parsed.netloc}"


def _safe_stripe_error(response: httpx.Response) -> str:
    try:
        message = (response.json().get("error") or {}).get("message")
        if message:
            return str(message)
    except ValueError:
        pass
    return f"Stripe returned HTTP {response.status_code}."


async def _stripe_post(
    config: ResidentPaymentsSettings,
    path: str,
    *,
    data: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {config.secret_api_key}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{_stripe_origin(config)}{path}", data=data, headers=headers)
    if response.status_code >= 400:
        raise ResidentAchError(_safe_stripe_error(response))
    try:
        return response.json()
    except ValueError as exc:
        raise ResidentAchError("Stripe returned an invalid response.") from exc


async def _stripe_delete(
    config: ResidentPaymentsSettings, path: str
) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(
            f"{_stripe_origin(config)}{path}",
            headers={"Authorization": f"Bearer {config.secret_api_key}"},
        )
    if response.status_code >= 400 and response.status_code != 404:
        raise ResidentAchError(_safe_stripe_error(response))


async def create_stripe_customer(
    config: ResidentPaymentsSettings,
    *,
    resident_id: uuid.UUID,
    name: str,
    email: str | None,
) -> str:
    data: dict[str, Any] = {"name": name, "metadata[resident_id]": str(resident_id)}
    if email:
        data["email"] = email
    body = await _stripe_post(
        config,
        "/v1/customers",
        data=data,
        idempotency_key=f"resident-customer:{resident_id}",
    )
    customer_id = str(body.get("id", ""))
    if not customer_id.startswith("cus_"):
        raise ResidentAchError("Stripe did not create a resident customer.")
    return customer_id


async def attach_bank_source(
    config: ResidentPaymentsSettings,
    *,
    customer_id: str,
    bank_account_token: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if not bank_account_token.startswith("btok_"):
        raise ResidentAchError("Plaid did not return a Stripe bank token.")
    body = await _stripe_post(
        config,
        f"/v1/customers/{customer_id}/sources",
        data={"source": bank_account_token},
        idempotency_key=idempotency_key,
    )
    if not str(body.get("id", "")).startswith("ba_"):
        raise ResidentAchError("Stripe did not attach a reusable bank source.")
    return body


async def detach_bank_source(
    config: ResidentPaymentsSettings, *, customer_id: str, source_id: str
) -> None:
    if customer_id.startswith("cus_") and source_id.startswith("ba_"):
        await _stripe_delete(config, f"/v1/customers/{customer_id}/sources/{source_id}")


async def exchange_and_attach(
    *,
    plaid_config: PlaidSettings,
    payment_config: ResidentPaymentsSettings,
    public_token: str,
    account_id: str,
    resident_id: uuid.UUID,
    resident_name: str,
    resident_email: str | None,
    existing_customer_id: str | None,
) -> tuple[str, dict[str, Any]]:
    client = PlaidClient(config=plaid_config)
    access_token = ""
    try:
        exchanged = await client.exchange_public_token(public_token)
        access_token = str(exchanged.get("access_token", ""))
        if not access_token:
            raise ResidentAchError("Plaid token exchange did not complete.")
        token_result = await client.create_stripe_bank_account_token(access_token, account_id)
        bank_token = str(token_result.get("bank_account_token", ""))
        customer_id = existing_customer_id or await create_stripe_customer(
            payment_config,
            resident_id=resident_id,
            name=resident_name,
            email=resident_email,
        )
        source = await attach_bank_source(
            payment_config,
            customer_id=customer_id,
            bank_account_token=bank_token,
            idempotency_key=f"resident-bank-source:{resident_id}:{account_id}",
        )
        return customer_id, source
    finally:
        if access_token:
            try:
                await client.remove_item(access_token)
            except Exception:
                pass


def verify_stripe_signature(
    payload: bytes, signature_header: str, secret: str, *, tolerance_seconds: int = 300
) -> bool:
    try:
        parts = dict(part.split("=", 1) for part in signature_header.split(","))
        timestamp = int(parts["t"])
        signature = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        return False
    signed = str(timestamp).encode("ascii") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

"""Billing-ledger service: upsert Stripe objects into the persisted ledger.

These helpers translate raw Stripe event/object payloads (dict-like) into the
``billing_*`` tables. They are idempotent: each upsert is keyed on the Stripe
object id, so replaying a webhook (or running reconciliation) updates the
existing row rather than duplicating it. All amounts arrive from Stripe as
integer cents and are stored as-is.

Resolution of an org is best-effort: rows reference Stripe customer/subscription
ids, and ``organization_id`` is back-filled when a matching Organization exists.
This keeps the ledger durable even for customers not yet linked to an org.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_ledger import (
    BillingCharge,
    BillingCoupon,
    BillingInvoice,
    BillingRefund,
    BillingSubscription,
)
from app.models.organization import Organization


def _ts(value: Any) -> datetime | None:
    """Convert a Stripe unix timestamp to an aware UTC datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


async def _resolve_org_id(db: AsyncSession, customer_id: str | None) -> Any:
    """Return the organization id for a Stripe customer id, if any."""
    if not customer_id:
        return None
    row = await db.execute(
        select(Organization.id).where(Organization.stripe_customer_id == customer_id)
    )
    return row.scalar_one_or_none()


async def upsert_subscription(db: AsyncSession, sub: dict[str, Any]) -> BillingSubscription:
    sub_id = sub.get("id")
    existing = (
        await db.execute(
            select(BillingSubscription).where(BillingSubscription.stripe_subscription_id == sub_id)
        )
    ).scalar_one_or_none()
    item = (sub.get("items", {}).get("data") or [{}])[0]
    price = item.get("price", {}) or {}
    customer_id = sub.get("customer")
    row = existing or BillingSubscription(stripe_subscription_id=sub_id)
    row.stripe_customer_id = customer_id
    row.organization_id = await _resolve_org_id(db, customer_id)
    row.status = sub.get("status") or "active"
    row.amount_cents = price.get("unit_amount") or 0
    row.quantity = item.get("quantity") or 1
    row.currency = (price.get("currency") or "usd")[:3]
    row.interval = (price.get("recurring", {}) or {}).get("interval") or "month"
    row.current_period_start = _ts(sub.get("current_period_start"))
    row.current_period_end = _ts(sub.get("current_period_end"))
    row.canceled_at = _ts(sub.get("canceled_at"))
    if not existing:
        db.add(row)
    return row


async def upsert_invoice(db: AsyncSession, inv: dict[str, Any]) -> BillingInvoice:
    inv_id = inv.get("id")
    existing = (
        await db.execute(select(BillingInvoice).where(BillingInvoice.stripe_invoice_id == inv_id))
    ).scalar_one_or_none()
    customer_id = inv.get("customer")
    row = existing or BillingInvoice(stripe_invoice_id=inv_id)
    row.stripe_customer_id = customer_id
    row.stripe_subscription_id = inv.get("subscription")
    row.organization_id = await _resolve_org_id(db, customer_id)
    row.number = inv.get("number")
    row.status = inv.get("status") or "draft"
    row.currency = (inv.get("currency") or "usd")[:3]
    row.subtotal_cents = inv.get("subtotal") or 0
    row.tax_cents = inv.get("tax") or 0
    row.total_cents = inv.get("total") or 0
    row.amount_paid_cents = inv.get("amount_paid") or 0
    row.amount_due_cents = inv.get("amount_due") or 0
    row.period_start = _ts(inv.get("period_start"))
    row.period_end = _ts(inv.get("period_end"))
    row.issued_at = _ts(inv.get("created"))
    if inv.get("status") == "paid":
        row.paid_at = _ts(inv.get("status_transitions", {}).get("paid_at")) or row.paid_at
    row.hosted_invoice_url = inv.get("hosted_invoice_url")
    if not existing:
        db.add(row)
    return row


async def upsert_charge(db: AsyncSession, charge: dict[str, Any]) -> BillingCharge:
    charge_id = charge.get("id")
    existing = (
        await db.execute(select(BillingCharge).where(BillingCharge.stripe_charge_id == charge_id))
    ).scalar_one_or_none()
    customer_id = charge.get("customer")
    row = existing or BillingCharge(stripe_charge_id=charge_id)
    row.stripe_customer_id = customer_id
    row.stripe_invoice_id = charge.get("invoice")
    row.organization_id = await _resolve_org_id(db, customer_id)
    row.status = charge.get("status") or "succeeded"
    row.amount_cents = charge.get("amount") or 0
    row.amount_refunded_cents = charge.get("amount_refunded") or 0
    row.currency = (charge.get("currency") or "usd")[:3]
    row.description = charge.get("description")
    row.failure_message = charge.get("failure_message")
    row.charged_at = _ts(charge.get("created"))
    if not existing:
        db.add(row)
    return row


async def upsert_refund(db: AsyncSession, refund: dict[str, Any]) -> BillingRefund:
    refund_id = refund.get("id")
    existing = (
        await db.execute(select(BillingRefund).where(BillingRefund.stripe_refund_id == refund_id))
    ).scalar_one_or_none()
    charge_id = refund.get("charge")
    row = existing or BillingRefund(stripe_refund_id=refund_id)
    row.stripe_charge_id = charge_id
    row.status = refund.get("status") or "succeeded"
    row.amount_cents = refund.get("amount") or 0
    row.currency = (refund.get("currency") or "usd")[:3]
    row.reason = refund.get("reason")
    row.refunded_at = _ts(refund.get("created"))
    # Inherit org from the underlying charge if known.
    if charge_id:
        org_id = (
            await db.execute(
                select(BillingCharge.organization_id).where(
                    BillingCharge.stripe_charge_id == charge_id
                )
            )
        ).scalar_one_or_none()
        row.organization_id = org_id
    if not existing:
        db.add(row)
    return row


async def upsert_coupon(db: AsyncSession, coupon: dict[str, Any]) -> BillingCoupon:
    coupon_id = coupon.get("id")
    existing = (
        await db.execute(select(BillingCoupon).where(BillingCoupon.stripe_coupon_id == coupon_id))
    ).scalar_one_or_none()
    row = existing or BillingCoupon(stripe_coupon_id=coupon_id)
    row.code = coupon.get("name") or coupon_id or "coupon"
    row.percent_off = int(coupon["percent_off"]) if coupon.get("percent_off") else None
    row.amount_off_cents = coupon.get("amount_off")
    row.currency = (coupon.get("currency") or "usd")[:3]
    row.duration = coupon.get("duration") or "once"
    row.is_active = bool(coupon.get("valid", True))
    if not existing:
        db.add(row)
    return row

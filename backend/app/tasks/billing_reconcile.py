"""Billing-ledger reconciliation job.

Periodically syncs the persisted ledger with Stripe so the super-admin engine
isn't wholly dependent on webhook delivery: it walks each org's Stripe customer,
upserts their subscription/invoices/charges, and computes a drift summary
(orgs whose plan/payment_status disagree with their latest Stripe subscription).
Runs daily; safely no-ops when Stripe isn't configured.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.organization import Organization
from app.services import billing_ledger_service as ledger

logger = logging.getLogger(__name__)

# Cap how many invoices/charges we pull per customer per run to bound API cost.
_PER_CUSTOMER_LIMIT = 20


async def reconcile_billing_ledger() -> dict:
    """Sync Stripe objects into the ledger and return a drift summary."""
    if not settings.STRIPE_SECRET_KEY:
        logger.info("billing reconcile skipped: Stripe not configured")
        return {"skipped": True, "synced": 0, "drift": []}

    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    synced = 0
    drift: list[dict] = []

    async with async_session() as db:
        orgs = (
            await db.execute(
                select(Organization).where(Organization.stripe_customer_id.is_not(None))
            )
        ).scalars().all()

        for org in orgs:
            cust = org.stripe_customer_id
            try:
                if org.stripe_subscription_id:
                    sub = stripe.Subscription.retrieve(org.stripe_subscription_id)
                    await ledger.upsert_subscription(db, dict(sub))
                    if sub.get("status") == "active" and org.payment_status != "active":
                        drift.append({"org_id": str(org.id), "name": org.name,
                                      "ledger_status": "active", "org_status": org.payment_status})
                for inv in stripe.Invoice.list(customer=cust, limit=_PER_CUSTOMER_LIMIT).get("data", []):
                    await ledger.upsert_invoice(db, dict(inv))
                for ch in stripe.Charge.list(customer=cust, limit=_PER_CUSTOMER_LIMIT).get("data", []):
                    await ledger.upsert_charge(db, dict(ch))
                synced += 1
            except Exception:
                logger.exception("billing reconcile failed for org %s", org.id)
        await db.commit()

    logger.info("billing reconcile synced %d orgs, %d drift", synced, len(drift))
    return {"skipped": False, "synced": synced, "drift": drift}

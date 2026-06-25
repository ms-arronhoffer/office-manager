from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User

router = APIRouter()

# Stripe subscription statuses that mean the org is fully active
_ACTIVE_STATUSES = {"active", "trialing"}
# Statuses that should trigger dunning (show warning banner, don't block yet)
_PAST_DUE_STATUSES = {"past_due", "incomplete"}
# Statuses that deactivate the org
_TERMINAL_STATUSES = {"canceled", "unpaid", "incomplete_expired"}


def _require_stripe() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server.",
        )
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _plan_from_price(price_id: str) -> str:
    if settings.STRIPE_PRICE_ID_PRO and price_id == settings.STRIPE_PRICE_ID_PRO:
        return "pro"
    if settings.STRIPE_PRICE_ID_ENTERPRISE and price_id == settings.STRIPE_PRICE_ID_ENTERPRISE:
        return "enterprise"
    return "pro"


async def _get_org(org_id, db: AsyncSession) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


# ─── GET /billing/subscription ────────────────────────────────────────────────

@router.get("/subscription")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current organization plan, seat usage, and payment status."""
    org = await _get_org(current_user.organization_id, db)

    seat_result = await db.execute(
        select(func.count()).select_from(User).where(
            User.organization_id == org.id,
            User.is_active.is_(True),
        )
    )
    seat_count = seat_result.scalar_one()

    return {
        "plan": org.plan,
        "is_active": org.is_active,
        "payment_status": org.payment_status,
        "stripe_customer_id": org.stripe_customer_id,
        "stripe_subscription_id": org.stripe_subscription_id,
        "trial_ends_at": org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        "max_seats": org.max_seats,
        "seat_count": seat_count,
        "billing_configured": bool(settings.STRIPE_SECRET_KEY),
    }


# ─── POST /billing/checkout ───────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str  # "pro" or "enterprise"


@router.post("/checkout")
async def create_checkout_session(
    payload: CheckoutRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for a plan upgrade. Redirects to Stripe."""
    _require_stripe()

    price_map = {
        "pro": settings.STRIPE_PRICE_ID_PRO,
        "enterprise": settings.STRIPE_PRICE_ID_ENTERPRISE,
    }
    price_id = price_map.get(payload.plan)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown plan '{payload.plan}' or price not configured.",
        )

    org = await _get_org(current_user.organization_id, db)

    session_kwargs: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{settings.FRONTEND_URL}/billing?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{settings.FRONTEND_URL}/billing",
        "metadata": {"org_id": str(org.id)},
    }
    if org.stripe_customer_id:
        session_kwargs["customer"] = org.stripe_customer_id
    else:
        session_kwargs["customer_email"] = current_user.email

    session = stripe.checkout.Session.create(**session_kwargs)
    return {"checkout_url": session.url}


# ─── POST /billing/portal ─────────────────────────────────────────────────────

@router.post("/portal")
async def create_portal_session(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Customer Portal session for billing management."""
    _require_stripe()
    org = await _get_org(current_user.organization_id, db)

    if not org.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No billing account found. Please subscribe to a plan first.",
        )

    session = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=f"{settings.FRONTEND_URL}/billing",
    )
    return {"portal_url": session.url}


# ─── POST /billing/webhooks ───────────────────────────────────────────────────

@router.post("/webhooks", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Stripe webhook handler — verifies HMAC signature and processes events."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing not configured")

    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(raw_body, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature")
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    event_type: str = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        # New subscription created via checkout
        org_id = obj.get("metadata", {}).get("org_id")
        if org_id:
            result = await db.execute(select(Organization).where(Organization.id == org_id))
            org = result.scalar_one_or_none()
            if org:
                org.stripe_customer_id = obj.get("customer")
                org.stripe_subscription_id = obj.get("subscription")
                if org.stripe_subscription_id:
                    sub = stripe.Subscription.retrieve(org.stripe_subscription_id)
                    price_id = sub["items"]["data"][0]["price"]["id"]
                    org.plan = _plan_from_price(price_id)
                org.payment_status = "active"
                org.is_active = True
                await db.commit()

    elif event_type == "customer.subscription.updated":
        # Plan change, renewal, or status change (e.g. trialing→active, active→past_due)
        sub_id = obj.get("id")
        if sub_id:
            result = await db.execute(
                select(Organization).where(Organization.stripe_subscription_id == sub_id)
            )
            org = result.scalar_one_or_none()
            if org:
                price_id = obj["items"]["data"][0]["price"]["id"]
                org.plan = _plan_from_price(price_id)
                sub_status = obj.get("status", "active")
                if sub_status in _ACTIVE_STATUSES:
                    org.payment_status = "active"
                    org.is_active = True
                elif sub_status in _PAST_DUE_STATUSES:
                    # Past due: keep org active but flag for dunning banner
                    org.payment_status = "past_due"
                    org.is_active = True
                elif sub_status in _TERMINAL_STATUSES:
                    # Canceled or unpaid after all retries: deactivate org
                    org.payment_status = "canceled"
                    org.is_active = False
                await db.commit()

    elif event_type == "customer.subscription.deleted":
        # Subscription fully canceled
        sub_id = obj.get("id")
        if sub_id:
            result = await db.execute(
                select(Organization).where(Organization.stripe_subscription_id == sub_id)
            )
            org = result.scalar_one_or_none()
            if org:
                org.plan = "starter"
                org.stripe_subscription_id = None
                org.payment_status = "canceled"
                org.is_active = False
                await db.commit()

    elif event_type == "invoice.payment_failed":
        # Payment attempt failed — enter dunning state (keep org active, show warning)
        customer_id = obj.get("customer")
        if customer_id:
            result = await db.execute(
                select(Organization).where(Organization.stripe_customer_id == customer_id)
            )
            org = result.scalar_one_or_none()
            if org and org.payment_status == "active":
                org.payment_status = "past_due"
                await db.commit()

    elif event_type == "invoice.payment_succeeded":
        # Payment recovered — clear dunning state
        customer_id = obj.get("customer")
        if customer_id:
            result = await db.execute(
                select(Organization).where(Organization.stripe_customer_id == customer_id)
            )
            org = result.scalar_one_or_none()
            if org and org.payment_status in ("past_due",):
                org.payment_status = "active"
                org.is_active = True
                await db.commit()

    return {"received": True}

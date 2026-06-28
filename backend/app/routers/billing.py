from __future__ import annotations
import logging

from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.services import entitlements as ent
from app.database import get_db
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.user import User
from app.services import billing_ledger_service as ledger
from app.utils.email_client import send_email

router = APIRouter()

logger = logging.getLogger(__name__)


async def _get_org_admin_emails(db: AsyncSession, org_id) -> list[str]:
    """Return email addresses of active admin users for an org."""
    result = await db.execute(
        select(User.email).where(
            User.organization_id == org_id,
            User.role == "admin",
            User.is_active.is_(True),
        )
    )
    return [r[0] for r in result.all()]


async def _send_billing_email(
    db: AsyncSession,
    org: Organization,
    template_name: str,
    subject: str,
    extra_ctx: dict | None = None,
) -> None:
    """Send a billing lifecycle email to all active admins of an org."""
    try:
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader("app/templates"))
        template = env.get_template(template_name)
        ctx = {"org_name": org.name, "billing_url": f"{settings.FRONTEND_URL}/billing"}
        if extra_ctx:
            ctx.update(extra_ctx)
        html_body = template.render(**ctx)
        recipients = await _get_org_admin_emails(db, org.id)
        for email in recipients:
            await send_email(to=email, subject=subject, html_body=html_body)
    except Exception as e:
        logger.warning("Failed to send billing email %s for %s: %s", template_name, org.name, e)


async def _notify_super_admins(
    db: AsyncSession,
    org: Organization,
    message: str,
) -> None:
    """Create an in-app Notification for every active super-admin."""
    try:
        super_admins = (
            await db.execute(
                select(User).where(User.is_super_admin.is_(True), User.is_active.is_(True))
            )
        ).scalars().all()
        for admin in super_admins:
            notif = Notification(
                user_id=admin.id,
                organization_id=org.id,
                kind="billing_alert",
                title=f"Billing alert: {org.name}",
                body=message,
            )
            db.add(notif)
        await db.commit()
    except Exception as e:
        logger.warning("Billing notification failed: %s", e)
        await db.rollback()


async def _notify_slack(message: str) -> None:
    """Post a message to the configured Slack webhook (best-effort)."""
    if not settings.SLACK_WEBHOOK_URL:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(settings.SLACK_WEBHOOK_URL, json={"text": message})
    except Exception as e:
        logger.warning("Slack notification failed: %s", e)


def _mark_active(org: Organization) -> None:
    """Transition an org to active and clear past-due grace tracking."""
    org.payment_status = "active"
    org.is_active = True
    org.past_due_since = None


def _mark_past_due(org: Organization) -> None:
    """Transition an org to past_due, stamping the grace-period start once."""
    org.payment_status = "past_due"
    org.is_active = True
    if org.past_due_since is None:
        org.past_due_since = datetime.now(timezone.utc)

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
                org.past_due_since = None
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
                    _mark_active(org)
                elif sub_status in _PAST_DUE_STATUSES:
                    # Past due: keep org active but start the grace-period clock
                    _mark_past_due(org)
                elif sub_status in _TERMINAL_STATUSES:
                    # Canceled or unpaid after all retries: deactivate org
                    org.payment_status = "canceled"
                    org.is_active = False
                    org.past_due_since = None
                await db.commit()
                if sub_status in _PAST_DUE_STATUSES:
                    await _notify_super_admins(db, org, f"Subscription past due for org '{org.name}'")
                    await _notify_slack(f":warning: Subscription past due for org *{org.name}*")

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
                org.past_due_since = None
                await db.commit()
                await _send_billing_email(
                    db, org,
                    "billing_account_suspended.html",
                    f"Your SwiftLease account has been suspended",
                )
                await _notify_super_admins(db, org, f"Subscription canceled for org '{org.name}' (plan: {org.plan})")
                await _notify_slack(f":red_circle: Subscription canceled for org *{org.name}*")

    elif event_type == "invoice.payment_failed":
        # Payment attempt failed — enter dunning state (keep org active, show warning)
        customer_id = obj.get("customer")
        if customer_id:
            result = await db.execute(
                select(Organization).where(Organization.stripe_customer_id == customer_id)
            )
            org = result.scalar_one_or_none()
            if org and org.payment_status == "active":
                _mark_past_due(org)
                await db.commit()
                await _send_billing_email(
                    db, org,
                    "billing_payment_failed.html",
                    f"Payment failed for {org.name} — action required",
                    extra_ctx={"grace_days": ent.PAST_DUE_GRACE_DAYS},
                )
                await _notify_super_admins(db, org, f"Payment failed for org '{org.name}' (plan: {org.plan})")
                await _notify_slack(f":warning: Payment failed for org *{org.name}* (plan: {org.plan})")

    elif event_type == "invoice.payment_succeeded":
        # Payment recovered — clear dunning state
        customer_id = obj.get("customer")
        if customer_id:
            result = await db.execute(
                select(Organization).where(Organization.stripe_customer_id == customer_id)
            )
            org = result.scalar_one_or_none()
            if org and org.payment_status in ("past_due",):
                _mark_active(org)
                await db.commit()
                await _send_billing_email(
                    db, org,
                    "billing_payment_recovered.html",
                    f"Payment successful — {org.name} account restored",
                )

    # ── Persist into the billing ledger (best-effort, idempotent) ──────────────
    try:
        if event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            await ledger.upsert_subscription(db, dict(obj))
        elif event_type in ("invoice.created", "invoice.finalized", "invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed"):
            await ledger.upsert_invoice(db, dict(obj))
        elif event_type in ("charge.succeeded", "charge.failed", "charge.refunded", "charge.updated"):
            await ledger.upsert_charge(db, dict(obj))
            for r in (obj.get("refunds", {}) or {}).get("data", []) or []:
                await ledger.upsert_refund(db, dict(r))
        elif event_type in ("charge.refund.updated", "refund.created", "refund.updated"):
            await ledger.upsert_refund(db, dict(obj))
        elif event_type in ("coupon.created", "coupon.updated", "coupon.deleted"):
            await ledger.upsert_coupon(db, dict(obj))
        await db.commit()
    except Exception:  # best-effort: never fail the webhook on ledger drift
        await db.rollback()
        logger.exception("billing ledger upsert failed for %s", event_type)

    return {"received": True}

"""Super-admin: billing oversight + Stripe cancel/restore."""
import csv
import io
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_console_role
from app.database import get_db
from app.models.billing_ledger import (
    BillingCharge, BillingCredit, BillingInvoice,
    BillingRefund, BillingSubscription,
)
from app.models.enterprise_activation_code import EnterpriseActivationCode
from app.models.organization import Organization
from app.models.platform_stripe_config import PlatformStripeConfig
from app.models.user import User
from app.services import billing_ledger_service as ledger
from app.services import stripe_settings as stripe_cfg
from app.services.activity_service import log_activity
from app.utils.crypto import decrypt_secret, encrypt_secret, mask_secret

router = APIRouter()


class BillingRow(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    payment_status: str
    is_active: bool
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    max_seats: int | None
    seat_count: int
    trial_ends_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedBilling(BaseModel):
    items: list[BillingRow]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("", response_model=PaginatedBilling)
async def list_billing(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    payment_status: str | None = Query(default=None),
    plan: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    stmt = select(Organization)
    if payment_status:
        stmt = stmt.where(Organization.payment_status == payment_status)
    if plan:
        stmt = stmt.where(Organization.plan == plan)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(Organization.created_at.desc()).offset(offset).limit(page_size))
    orgs = result.scalars().all()

    # Seat counts
    org_ids = [o.id for o in orgs]
    seat_counts: dict[uuid.UUID, int] = {}
    if org_ids:
        seat_rows = await db.execute(
            select(User.organization_id, func.count(User.id))
            .where(User.organization_id.in_(org_ids), User.is_active.is_(True))
            .group_by(User.organization_id)
        )
        seat_counts = {r[0]: r[1] for r in seat_rows.all()}

    items = [
        BillingRow(
            id=o.id,
            name=o.name,
            plan=o.plan,
            payment_status=o.payment_status,
            is_active=o.is_active,
            stripe_customer_id=o.stripe_customer_id,
            stripe_subscription_id=o.stripe_subscription_id,
            max_seats=o.max_seats,
            seat_count=seat_counts.get(o.id, 0),
            trial_ends_at=o.trial_ends_at,
            created_at=o.created_at,
        )
        for o in orgs
    ]
    return PaginatedBilling(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


class DunningRow(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    payment_status: str
    past_due_since: datetime | None
    overdue_days: int
    seat_count: int
    trial_ends_at: datetime | None
    stripe_customer_id: str | None


@router.get("/dunning-queue", response_model=list[DunningRow])
async def dunning_queue(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    rows = (
        await db.execute(
            select(Organization)
            .where(Organization.payment_status == "past_due")
            .order_by(Organization.past_due_since.asc().nullslast(), Organization.created_at.asc())
        )
    ).scalars().all()
    org_ids = [o.id for o in rows]
    seat_counts: dict[uuid.UUID, int] = {}
    if org_ids:
        seat_rows = await db.execute(
            select(User.organization_id, func.count(User.id))
            .where(User.organization_id.in_(org_ids), User.is_active.is_(True))
            .group_by(User.organization_id)
        )
        seat_counts = {r[0]: r[1] for r in seat_rows.all()}
    now = datetime.now(timezone.utc)
    return [
        DunningRow(
            id=o.id,
            name=o.name,
            plan=o.plan,
            payment_status=o.payment_status,
            past_due_since=o.past_due_since,
            overdue_days=max(0, (now - (o.past_due_since or now)).days),
            seat_count=seat_counts.get(o.id, 0),
            trial_ends_at=o.trial_ends_at,
            stripe_customer_id=o.stripe_customer_id,
        )
        for o in rows
    ]


@router.post("/{org_id}/cancel", response_model=BillingRow)
async def cancel_subscription(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Cancel Stripe subscription if configured
    stripe_key = await stripe_cfg.resolve_stripe_secret_key(db)
    if org.stripe_subscription_id and stripe_key:
        try:
            import stripe
            stripe.api_key = stripe_key
            stripe.Subscription.cancel(org.stripe_subscription_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe cancellation failed: {exc}",
            ) from exc

    org.is_active = False
    org.payment_status = "canceled"
    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes={"action": "subscription_canceled"},
    )

    seat_rows = await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id, User.is_active.is_(True))
    )
    seat_count = seat_rows.scalar_one()

    return BillingRow(
        id=org.id,
        name=org.name,
        plan=org.plan,
        payment_status=org.payment_status,
        is_active=org.is_active,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        max_seats=org.max_seats,
        seat_count=seat_count,
        trial_ends_at=org.trial_ends_at,
        created_at=org.created_at,
    )


@router.post("/{org_id}/restore", response_model=BillingRow)
async def restore_subscription(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org.is_active = True
    org.payment_status = "active"
    await db.commit()
    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="organization",
        entity_id=org_id,
        entity_label=org.name,
        changes={"action": "subscription_restored"},
    )

    seat_rows = await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id, User.is_active.is_(True))
    )
    seat_count = seat_rows.scalar_one()

    return BillingRow(
        id=org.id,
        name=org.name,
        plan=org.plan,
        payment_status=org.payment_status,
        is_active=org.is_active,
        stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id,
        max_seats=org.max_seats,
        seat_count=seat_count,
        trial_ends_at=org.trial_ends_at,
        created_at=org.created_at,
    )


# ─── Per-org billing detail ─────────────────────────────────────────────────────

class LedgerRow(BaseModel):
    id: uuid.UUID
    status: str
    amount_cents: int
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BillingDetail(BaseModel):
    org_id: uuid.UUID
    name: str
    plan: str
    payment_status: str
    stripe_customer_id: str | None
    subscriptions: list[dict]
    invoices: list[dict]
    charges: list[dict]
    refunds: list[dict]
    credits: list[dict]
    credit_balance_cents: int


async def _get_org_or_404(org_id: uuid.UUID, db: AsyncSession) -> Organization:
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.get("/{org_id}/detail", response_model=BillingDetail)
async def billing_detail(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    """Full per-org billing history from the persisted ledger: subscriptions,
    invoices, charges, refunds, and manual credits with running credit balance."""
    org = await _get_org_or_404(org_id, db)
    cust = org.stripe_customer_id

    subs = (await db.execute(
        select(BillingSubscription).where(BillingSubscription.organization_id == org_id)
        .order_by(BillingSubscription.created_at.desc())
    )).scalars().all()
    invs = (await db.execute(
        select(BillingInvoice).where(BillingInvoice.organization_id == org_id)
        .order_by(BillingInvoice.issued_at.desc().nullslast()).limit(100)
    )).scalars().all()
    charges = (await db.execute(
        select(BillingCharge).where(BillingCharge.organization_id == org_id)
        .order_by(BillingCharge.charged_at.desc().nullslast()).limit(100)
    )).scalars().all()
    refunds = (await db.execute(
        select(BillingRefund).where(BillingRefund.organization_id == org_id)
        .order_by(BillingRefund.refunded_at.desc().nullslast()).limit(100)
    )).scalars().all()
    credits = (await db.execute(
        select(BillingCredit).where(BillingCredit.organization_id == org_id)
        .order_by(BillingCredit.created_at.desc())
    )).scalars().all()
    credit_balance = sum(c.amount_cents for c in credits)

    def _s(rows, fields):
        return [{f: getattr(r, f) for f in fields} for r in rows]

    return BillingDetail(
        org_id=org.id, name=org.name, plan=org.plan, payment_status=org.payment_status,
        stripe_customer_id=cust,
        subscriptions=_s(subs, ["id", "status", "plan", "amount_cents", "quantity", "currency", "interval", "current_period_end"]),
        invoices=_s(invs, ["id", "number", "status", "total_cents", "tax_cents", "amount_due_cents", "issued_at", "paid_at"]),
        charges=_s(charges, ["id", "status", "amount_cents", "amount_refunded_cents", "currency", "charged_at"]),
        refunds=_s(refunds, ["id", "status", "amount_cents", "currency", "reason", "refunded_at"]),
        credits=_s(credits, ["id", "amount_cents", "currency", "reason", "created_at"]),
        credit_balance_cents=credit_balance,
    )


# ─── Manual credit ──────────────────────────────────────────────────────────────

class CreditRequest(BaseModel):
    amount_cents: int
    reason: str | None = None
    currency: str = "usd"


@router.post("/{org_id}/credit", status_code=status.HTTP_201_CREATED)
async def issue_credit(
    org_id: uuid.UUID,
    payload: CreditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Issue a manual account credit/adjustment (positive grants, negative debits)."""
    org = await _get_org_or_404(org_id, db)
    credit = BillingCredit(
        organization_id=org.id, source="manual", amount_cents=payload.amount_cents,
        currency=payload.currency[:3], reason=payload.reason, created_by_id=current_user.id,
    )
    db.add(credit)
    await db.commit()
    await log_activity(db, user=current_user, action="created", entity_type="organization",
                       entity_id=org_id, entity_label=org.name,
                       changes={"action": "billing_credit", "amount_cents": payload.amount_cents})
    return {"id": str(credit.id), "amount_cents": credit.amount_cents}


# ─── Extend trial ───────────────────────────────────────────────────────────────

class ExtendTrialRequest(BaseModel):
    days: int


@router.post("/{org_id}/extend-trial", response_model=BillingRow)
async def extend_trial(
    org_id: uuid.UUID,
    payload: ExtendTrialRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Extend (or set) an org's trial end date by ``days`` from the current end."""
    if payload.days <= 0 or payload.days > 365:
        raise HTTPException(status_code=400, detail="days must be 1-365")
    org = await _get_org_or_404(org_id, db)
    base = org.trial_ends_at or datetime.now(timezone.utc)
    org.trial_ends_at = base + timedelta(days=payload.days)
    await db.commit()
    await log_activity(db, user=current_user, action="updated", entity_type="organization",
                       entity_id=org_id, entity_label=org.name,
                       changes={"action": "trial_extended", "days": payload.days})
    seat_count = (await db.execute(
        select(func.count(User.id)).where(User.organization_id == org_id, User.is_active.is_(True))
    )).scalar_one()
    return BillingRow(
        id=org.id, name=org.name, plan=org.plan, payment_status=org.payment_status,
        is_active=org.is_active, stripe_customer_id=org.stripe_customer_id,
        stripe_subscription_id=org.stripe_subscription_id, max_seats=org.max_seats,
        seat_count=seat_count, trial_ends_at=org.trial_ends_at, created_at=org.created_at,
    )


# ─── Refund a charge ────────────────────────────────────────────────────────────

class RefundRequest(BaseModel):
    stripe_charge_id: str
    amount_cents: int | None = None
    reason: str | None = None


@router.post("/{org_id}/refund", status_code=status.HTTP_201_CREATED)
async def issue_refund(
    org_id: uuid.UUID,
    payload: RefundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Refund a charge via Stripe and mirror the result into the ledger."""
    await _get_org_or_404(org_id, db)
    stripe_key = await stripe_cfg.resolve_stripe_secret_key(db)
    if not stripe_key:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    import stripe
    stripe.api_key = stripe_key
    kwargs: dict = {"charge": payload.stripe_charge_id}
    if payload.amount_cents:
        kwargs["amount"] = payload.amount_cents
    if payload.reason:
        kwargs["reason"] = payload.reason
    try:
        refund = stripe.Refund.create(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Stripe refund failed: {exc}") from exc
    await ledger.upsert_refund(db, dict(refund))
    await db.commit()
    await log_activity(db, user=current_user, action="created", entity_type="organization",
                       entity_id=org_id, entity_label=str(org_id),
                       changes={"action": "refund", "charge": payload.stripe_charge_id})
    return {"refund_id": refund.get("id"), "amount_cents": refund.get("amount")}


# ─── Financial CSV exports ──────────────────────────────────────────────────────

@router.get("/export/invoices")
async def export_invoices(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    """Export invoices (incl. tax) to CSV for finance reconciliation (max 10k)."""
    stmt = select(BillingInvoice)
    if date_from:
        stmt = stmt.where(BillingInvoice.issued_at >= date_from)
    if date_to:
        stmt = stmt.where(BillingInvoice.issued_at <= date_to)
    rows = (await db.execute(stmt.order_by(BillingInvoice.issued_at.desc().nullslast()).limit(10_000))).scalars().all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "number", "organization_id", "status", "currency", "subtotal_cents",
                "tax_cents", "total_cents", "amount_paid_cents", "amount_due_cents", "issued_at", "paid_at"])
    for r in rows:
        w.writerow([r.id, r.number, r.organization_id, r.status, r.currency, r.subtotal_cents,
                    r.tax_cents, r.total_cents, r.amount_paid_cents, r.amount_due_cents, r.issued_at, r.paid_at])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=invoices.csv"})


@router.get("/reconcile", response_model=dict)
async def reconcile_report(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    """Detect drift between org payment_status and the latest ledger subscription
    status. Read-only; surfaces orgs whose snapshot disagrees with the ledger."""
    subs = (await db.execute(
        select(BillingSubscription).where(BillingSubscription.organization_id.is_not(None))
    )).scalars().all()
    latest: dict = {}
    for s in subs:
        cur = latest.get(s.organization_id)
        if not cur or (s.current_period_end and (not cur.current_period_end or s.current_period_end > cur.current_period_end)):
            latest[s.organization_id] = s
    drift = []
    if latest:
        orgs = (await db.execute(select(Organization).where(Organization.id.in_(latest.keys())))).scalars().all()
        active = {"active", "trialing"}
        for o in orgs:
            sub = latest[o.id]
            sub_active = sub.status in active
            org_active = o.payment_status == "active"
            if sub_active != org_active:
                drift.append({"org_id": str(o.id), "name": o.name,
                              "ledger_status": sub.status, "org_status": o.payment_status})
    return {"orgs_with_subscriptions": len(latest), "drift_count": len(drift), "drift": drift}


# ─── Stripe integration credentials ─────────────────────────────────────────────
#
# A super-admin control for establishing/rotating the platform's Stripe
# credentials from the console instead of requiring deploy access. Secret values
# are encrypted at rest and never returned — only a masked hint is exposed.

class StripeConfigOut(BaseModel):
    configured: bool
    is_enabled: bool
    secret_key_hint: str | None = None
    webhook_secret_hint: str | None = None
    publishable_key: str | None = None
    price_id_starter: str | None = None
    price_id_pro: str | None = None
    product_id_enterprise: str | None = None
    # True when the effective value comes from an environment variable rather
    # than the stored config (helps the console explain where creds originate).
    secret_key_from_env: bool = False
    last_verified_at: datetime | None = None
    last_verify_ok: bool | None = None
    last_verify_error: str | None = None


class StripeConfigIn(BaseModel):
    # Secrets are optional so a save can update non-secret fields (or toggle
    # is_enabled) without resubmitting the secret. Send an empty string to clear.
    secret_key: str | None = None
    webhook_secret: str | None = None
    publishable_key: str | None = None
    price_id_starter: str | None = None
    price_id_pro: str | None = None
    product_id_enterprise: str | None = None
    is_enabled: bool | None = None


class StripeTestOut(BaseModel):
    ok: bool
    error: str | None = None


async def _stripe_config_out(db: AsyncSession) -> StripeConfigOut:
    cfg = await stripe_cfg.get_stripe_config(db)
    resolved = await stripe_cfg.resolve_stripe_settings(db)
    stored_secret = cfg.secret_key_encrypted if cfg else None
    stored_webhook = cfg.webhook_secret_encrypted if cfg else None
    return StripeConfigOut(
        configured=resolved.configured,
        is_enabled=cfg.is_enabled if cfg else True,
        secret_key_hint=mask_secret(decrypt_secret(stored_secret)) if stored_secret else None,
        webhook_secret_hint=mask_secret(decrypt_secret(stored_webhook)) if stored_webhook else None,
        publishable_key=cfg.publishable_key if cfg else None,
        price_id_starter=resolved.price_id_starter or None,
        price_id_pro=resolved.price_id_pro or None,
        product_id_enterprise=resolved.product_id_enterprise or None,
        secret_key_from_env=bool(resolved.secret_key) and not (cfg and cfg.is_enabled and stored_secret),
        last_verified_at=cfg.last_verified_at if cfg else None,
        last_verify_ok=cfg.last_verify_ok if cfg else None,
        last_verify_error=cfg.last_verify_error if cfg else None,
    )


@router.get("/stripe-config", response_model=StripeConfigOut)
async def get_stripe_config(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    """Return the platform Stripe configuration (secrets masked)."""
    return await _stripe_config_out(db)


@router.put("/stripe-config", response_model=StripeConfigOut)
async def save_stripe_config(
    payload: StripeConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Create or update the platform Stripe credentials.

    Secret fields are only changed when a non-``None`` value is supplied; an
    empty string clears the stored secret (falling back to env). Non-secret
    fields follow the same convention.
    """
    cfg = await stripe_cfg.get_stripe_config(db)
    if cfg is None:
        cfg = PlatformStripeConfig()
        db.add(cfg)

    secret_changed = False
    if payload.secret_key is not None:
        cfg.secret_key_encrypted = encrypt_secret(payload.secret_key) if payload.secret_key.strip() else None
        secret_changed = True
    if payload.webhook_secret is not None:
        cfg.webhook_secret_encrypted = (
            encrypt_secret(payload.webhook_secret) if payload.webhook_secret.strip() else None
        )
    if payload.publishable_key is not None:
        cfg.publishable_key = payload.publishable_key.strip() or None
    if payload.price_id_starter is not None:
        cfg.price_id_starter = payload.price_id_starter.strip() or None
    if payload.price_id_pro is not None:
        cfg.price_id_pro = payload.price_id_pro.strip() or None
    if payload.product_id_enterprise is not None:
        cfg.product_id_enterprise = payload.product_id_enterprise.strip() or None
    if payload.is_enabled is not None:
        cfg.is_enabled = payload.is_enabled
    cfg.updated_by_id = current_user.id

    if secret_changed:
        # Credentials changed — clear any stale verification state.
        cfg.last_verified_at = None
        cfg.last_verify_ok = None
        cfg.last_verify_error = None

    await db.commit()
    await log_activity(
        db, user=current_user, action="updated", entity_type="platform_stripe_config",
        entity_id=cfg.id, entity_label="Stripe integration",
        changes={"action": "stripe_config_saved"},
    )
    return await _stripe_config_out(db)


@router.post("/stripe-config/test", response_model=StripeTestOut)
async def test_stripe_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Verify the effective Stripe secret key by making a lightweight API call."""
    cfg = await stripe_cfg.get_stripe_config(db)
    resolved = await stripe_cfg.resolve_stripe_settings(db)
    ok = False
    error: str | None = None
    if not resolved.secret_key:
        error = "No Stripe secret key configured."
    else:
        try:
            import stripe
            stripe.api_key = resolved.secret_key
            stripe.Balance.retrieve()
            ok = True
        except Exception as exc:  # pragma: no cover - network/credential errors
            error = str(exc)

    if cfg is not None:
        cfg.last_verified_at = datetime.now(timezone.utc)
        cfg.last_verify_ok = ok
        cfg.last_verify_error = error
        await db.commit()
    return StripeTestOut(ok=ok, error=error)


# ─── Enterprise activation codes ────────────────────────────────────────────────
#
# Enterprise is custom-priced per subscriber. Sales negotiates a bespoke price,
# provisions it as a Stripe Price under the Enterprise Product, then mints an
# opaque activation code here that maps to that price. The org admin enters the
# code on their billing page to self-activate the negotiated Enterprise plan.

class EnterpriseCodeIn(BaseModel):
    stripe_price_id: str
    organization_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    # Optional custom code; a secure random code is generated when omitted.
    code: str | None = None
    notes: str | None = None


class EnterpriseCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    stripe_price_id: str
    organization_id: uuid.UUID | None
    is_active: bool
    expires_at: datetime | None
    redeemed_at: datetime | None
    redeemed_by_org_id: uuid.UUID | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _generate_activation_code() -> str:
    """Generate a readable, hard-to-guess Enterprise activation code."""
    return f"ENT-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"


@router.get("/enterprise-codes", response_model=list[EnterpriseCodeOut])
async def list_enterprise_codes(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "finance")),
):
    """List all Enterprise activation codes (most recent first)."""
    rows = (
        await db.execute(
            select(EnterpriseActivationCode).order_by(EnterpriseActivationCode.created_at.desc())
        )
    ).scalars().all()
    return [EnterpriseCodeOut.model_validate(r) for r in rows]


@router.post("/enterprise-codes", response_model=EnterpriseCodeOut, status_code=status.HTTP_201_CREATED)
async def create_enterprise_code(
    payload: EnterpriseCodeIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Mint an Enterprise activation code mapping to a bespoke Stripe Price."""
    price_id = payload.stripe_price_id.strip()
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A Stripe price ID is required."
        )

    if payload.organization_id is not None:
        org = (
            await db.execute(select(Organization).where(Organization.id == payload.organization_id))
        ).scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    code_str = (payload.code or "").strip() or _generate_activation_code()
    existing = (
        await db.execute(
            select(EnterpriseActivationCode).where(EnterpriseActivationCode.code == code_str)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That activation code already exists."
        )

    obj = EnterpriseActivationCode(
        code=code_str,
        stripe_price_id=price_id,
        organization_id=payload.organization_id,
        expires_at=payload.expires_at,
        notes=(payload.notes or None),
        created_by_id=current_user.id,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    await log_activity(
        db, user=current_user, action="created", entity_type="enterprise_activation_code",
        entity_id=obj.id, entity_label=obj.code,
        changes={"action": "enterprise_code_minted", "stripe_price_id": price_id},
    )
    return EnterpriseCodeOut.model_validate(obj)


@router.post("/enterprise-codes/{code_id}/revoke", response_model=EnterpriseCodeOut)
async def revoke_enterprise_code(
    code_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "finance")),
):
    """Deactivate an Enterprise activation code so it can no longer be redeemed."""
    obj = (
        await db.execute(
            select(EnterpriseActivationCode).where(EnterpriseActivationCode.id == code_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activation code not found")
    obj.is_active = False
    await db.commit()
    await db.refresh(obj)
    await log_activity(
        db, user=current_user, action="updated", entity_type="enterprise_activation_code",
        entity_id=obj.id, entity_label=obj.code,
        changes={"action": "enterprise_code_revoked"},
    )
    return EnterpriseCodeOut.model_validate(obj)

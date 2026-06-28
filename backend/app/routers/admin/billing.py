"""Super-admin: billing oversight + Stripe cancel/restore."""
import csv
import io
import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_super_admin
from app.config import settings
from app.database import get_db
from app.models.billing_ledger import (
    BillingCharge, BillingCredit, BillingInvoice,
    BillingRefund, BillingSubscription,
)
from app.models.organization import Organization
from app.models.user import User
from app.services import billing_ledger_service as ledger
from app.services.activity_service import log_activity

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
    _: User = Depends(require_super_admin()),
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


@router.post("/{org_id}/cancel", response_model=BillingRow)
async def cancel_subscription(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin()),
):
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Cancel Stripe subscription if configured
    if org.stripe_subscription_id and settings.STRIPE_SECRET_KEY:
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
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
    current_user: User = Depends(require_super_admin()),
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
    _: User = Depends(require_super_admin()),
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
    current_user: User = Depends(require_super_admin()),
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
    current_user: User = Depends(require_super_admin()),
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
    current_user: User = Depends(require_super_admin()),
):
    """Refund a charge via Stripe and mirror the result into the ledger."""
    await _get_org_or_404(org_id, db)
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
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
    _: User = Depends(require_super_admin()),
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
    _: User = Depends(require_super_admin()),
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

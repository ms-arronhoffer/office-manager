"""Resident portal — token-gated endpoints for external resident access (Phase 2.2).

Extends the existing portal-token pattern (client & vendor portals) to residents.
A staff member mints a single-use invite; the resident redeems it for a
persistent ``X-Resident-Token`` credential used to:

  * view their profile, leases (unit + rent/deposit terms), and documents,
  * submit maintenance requests that feed the existing ticketing system,
  * view a simple balance summary (rent/deposit; live payment history arrives
    with Phase 2.3), and
  * read announcements addressed to them.

Portal accounts reuse :class:`ClientPortalAccount` with ``entity_type="resident"``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.auth.portal_sessions import PortalExchangeRequest, set_portal_cookie
from app.config import settings
from app.database import get_db
from app.models.announcement import Announcement, AnnouncementRecipient
from app.models.attachment import Attachment
from app.models.client_portal_account import ClientPortalAccount
from app.models.customer_invoice import CustomerInvoice
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.resident import (
    RentalUnit,
    Resident,
    ResidentLease,
    ResidentLeaseOccupant,
)
from app.models.resident_payment_method import ResidentPaymentMethod
from app.models.resident_payment_attempt import ResidentPaymentAttempt
from app.models.user import User
from app.schemas.attachment import AttachmentResponse
from app.services import ar_service
from app.services import rent_service as rent_svc
from app.services.rent_service import RentError
from app.services import resident_ach_service
from app.utils import payment_processor
from app.utils.rls import set_session_org, set_system_bypass

log = logging.getLogger(__name__)

router = APIRouter()

_RESIDENT_ENTITY_TYPE = "resident"
_TOKEN_TTL_DAYS = 90
_SIGNUP_TTL_DAYS = 14
_RESIDENT_REQUEST_CATEGORY = "Resident Request"


# ─── Schemas ──────────────────────────────────────────────────────────────────

class InviteResponse(BaseModel):
    signup_token: str
    signup_url: str
    expires_at: datetime


class SignupRequest(BaseModel):
    token: str


class PortalSession(BaseModel):
    portal_token: str
    portal_url: str
    expires_at: datetime


class ResidentProfile(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    status: str

    model_config = {"from_attributes": True}


class PortalLease(BaseModel):
    id: uuid.UUID
    name: str | None
    status: str
    start_date: date | None
    end_date: date | None
    move_in_date: date | None
    rent_amount: Decimal | None
    rent_frequency: str
    security_deposit: Decimal | None
    currency: str
    unit_number: str | None
    unit_name: str | None
    autopay_enabled: bool = False
    autopay_payment_method_id: uuid.UUID | None = None
    autopay_last_status: str | None = None
    autopay_last_attempt_at: datetime | None = None
    autopay_last_detail: str | None = None


class BalanceSummary(BaseModel):
    currency: str
    monthly_rent: Decimal
    security_deposit: Decimal
    balance_due: Decimal


class PaymentConfigResponse(BaseModel):
    configured: bool
    provider: str
    publishable_key: str
    plaid_ach_available: bool = False
    plaid_ach_unavailable_reason: str | None = None


class PaymentMethodCreate(BaseModel):
    """A method saved from a processor token. Never carries a card/bank number."""

    processor_token: str
    brand: str | None = None
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    is_default: bool = False


class PaymentMethodResponse(BaseModel):
    id: uuid.UUID
    processor: str
    method_type: str
    status: str
    brand: str | None
    bank_name: str | None
    account_type: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalPaymentCreate(BaseModel):
    amount: Decimal
    payment_method_id: uuid.UUID | None = None
    method: str = "card"
    # Client-generated, stable for one payment attempt and resent on retry.
    idempotency_key: str | None = Field(default=None, max_length=200)


class PortalPaymentResponse(BaseModel):
    amount_applied: Decimal
    captured: bool
    processor_status: str
    detail: str | None = None
    receipt_ids: list[uuid.UUID]
    balance: BalanceSummary
    attempt_id: uuid.UUID | None = None


class AutopayUpdate(BaseModel):
    enabled: bool
    payment_method_id: uuid.UUID | None = None
    lease_id: uuid.UUID | None = None
    recurring_consent_accepted: bool = False


class AchLinkTokenRequest(BaseModel):
    consent_accepted: bool


class AchLinkTokenResponse(BaseModel):
    link_token: str


class AchExchangeRequest(BaseModel):
    public_token: str
    account_id: str
    institution_name: str | None = None
    is_default: bool = False
    consent_accepted: bool


class AutopayResponse(BaseModel):
    lease_id: uuid.UUID
    autopay_enabled: bool
    autopay_payment_method_id: uuid.UUID | None


class MaintenanceRequestCreate(BaseModel):
    subject: str
    description: str
    priority: str = "medium"


class PortalTicket(BaseModel):
    id: uuid.UUID
    subject: str
    description: str
    status: str
    priority: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalAnnouncement(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    sent_at: datetime | None
    read_at: datetime | None


# ─── Token helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_resident_account(
    x_resident_token: str = Header(None, alias="X-Resident-Token"),
    resident_cookie: str | None = Cookie(default=None, alias="om_resident_portal"),
    db: AsyncSession = Depends(get_db),
) -> ClientPortalAccount:
    x_resident_token = resident_cookie or x_resident_token
    if not x_resident_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing resident portal token")
    await set_system_bypass(db)
    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.portal_token == x_resident_token,
                ClientPortalAccount.entity_type == _RESIDENT_ENTITY_TYPE,
            )
        )
    ).scalar_one_or_none()
    if account is None or account.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid resident portal token")
    expires = _aware(account.portal_token_expires_at)
    if expires is not None and expires < _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Resident portal token expired")
    await set_session_org(db, account.organization_id)
    account.last_active_at = _now()
    return account


@router.post("/resident-portal/exchange", status_code=status.HTTP_204_NO_CONTENT)
async def exchange_resident_token(
    payload: PortalExchangeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    account = await get_resident_account(x_resident_token=payload.token, resident_cookie=None, db=db)
    expires = _aware(account.portal_token_expires_at)
    max_age = max(1, int((expires - _now()).total_seconds())) if expires else _TOKEN_TTL_DAYS * 86400
    set_portal_cookie(response, "om_resident_portal", payload.token, "/api/v1/resident-portal", max_age)


async def _resident_for(db: AsyncSession, account: ClientPortalAccount) -> Resident:
    resident = (
        await db.execute(
            select(Resident).where(
                Resident.id == account.entity_id,
                Resident.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if resident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    return resident


# ─── Staff: invite ────────────────────────────────────────────────────────────

@router.post("/resident-portal/invite", response_model=InviteResponse)
async def invite_resident(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Mint (or refresh) a single-use portal invite for a resident."""
    resident_id = payload.get("resident_id")
    if not resident_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="resident_id is required")
    resident = (
        await db.execute(
            select(Resident).where(
                Resident.id == uuid.UUID(str(resident_id)),
                Resident.organization_id == current_user.organization_id,
                Resident.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if resident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")

    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.entity_type == _RESIDENT_ENTITY_TYPE,
                ClientPortalAccount.entity_id == resident.id,
                ClientPortalAccount.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()

    signup_token = secrets.token_hex(32)
    expires = _now() + timedelta(days=_SIGNUP_TTL_DAYS)
    if account is None:
        account = ClientPortalAccount(
            organization_id=current_user.organization_id,
            entity_type=_RESIDENT_ENTITY_TYPE,
            entity_id=resident.id,
        )
        db.add(account)
    account.signup_token = signup_token
    account.signup_token_expires_at = expires
    account.revoked_at = None
    await db.commit()
    return InviteResponse(
        signup_token=signup_token,
        signup_url=f"/resident-portal/signup?token={signup_token}",
        expires_at=expires,
    )


# ─── Public: signup ───────────────────────────────────────────────────────────

@router.post("/resident-portal/signup", response_model=PortalSession)
async def resident_signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
):
    await set_system_bypass(db)
    account = (
        await db.execute(
            select(ClientPortalAccount).where(
                ClientPortalAccount.signup_token == payload.token,
                ClientPortalAccount.entity_type == _RESIDENT_ENTITY_TYPE,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid signup token")
    await set_session_org(db, account.organization_id)
    expires = _aware(account.signup_token_expires_at)
    if expires is not None and expires < _now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signup token expired")

    portal_token = secrets.token_hex(32)
    portal_expires = _now() + timedelta(days=_TOKEN_TTL_DAYS)
    account.portal_token = portal_token
    account.portal_token_expires_at = portal_expires
    account.signup_token = None
    account.signup_token_expires_at = None
    account.activated_at = _now()
    await db.commit()
    return PortalSession(
        portal_token=portal_token,
        portal_url=f"/resident-portal?token={portal_token}",
        expires_at=portal_expires,
    )


# ─── Resident: profile / leases / balance ─────────────────────────────────────

@router.get("/resident-portal/me", response_model=ResidentProfile)
async def portal_me(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    resident = await _resident_for(db, account)
    await db.commit()
    return ResidentProfile.model_validate(resident)


async def _load_resident_leases(
    db: AsyncSession, resident_id: uuid.UUID
) -> list[ResidentLease]:
    return list(
        (
            await db.execute(
                select(ResidentLease)
                .join(
                    ResidentLeaseOccupant,
                    ResidentLeaseOccupant.lease_id == ResidentLease.id,
                )
                .where(
                    ResidentLeaseOccupant.resident_id == resident_id,
                    ResidentLease.is_deleted.is_(False),
                )
                .options(selectinload(ResidentLease.unit))
                .order_by(ResidentLease.created_at.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )


@router.get("/resident-portal/leases", response_model=list[PortalLease])
async def portal_leases(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    leases = await _load_resident_leases(db, account.entity_id)
    lease_ids = [lease.id for lease in leases]
    attempts = (
        await db.execute(
            select(ResidentPaymentAttempt)
            .where(
                ResidentPaymentAttempt.organization_id == account.organization_id,
                ResidentPaymentAttempt.resident_id == account.entity_id,
                ResidentPaymentAttempt.lease_id.in_(lease_ids),
                ResidentPaymentAttempt.idempotency_key.startswith("resident-autopay:"),
            )
            .order_by(ResidentPaymentAttempt.created_at.desc())
        )
    ).scalars().all() if lease_ids else []
    latest_attempts = {}
    for attempt in attempts:
        latest_attempts.setdefault(attempt.lease_id, attempt)
    await db.commit()
    return [
        PortalLease(
            id=l.id,
            name=l.name,
            status=l.status,
            start_date=l.start_date,
            end_date=l.end_date,
            move_in_date=l.move_in_date,
            rent_amount=l.rent_amount,
            rent_frequency=l.rent_frequency,
            security_deposit=l.security_deposit,
            currency=l.currency,
            unit_number=l.unit.unit_number if l.unit else None,
            unit_name=l.unit.name if l.unit else None,
            autopay_enabled=bool(l.autopay_enabled),
            autopay_payment_method_id=l.autopay_payment_method_id,
            autopay_last_status=(latest_attempts[l.id].status if l.id in latest_attempts else None),
            autopay_last_attempt_at=(latest_attempts[l.id].created_at if l.id in latest_attempts else None),
            autopay_last_detail=(
                latest_attempts[l.id].failure_detail if l.id in latest_attempts else None
            ),
        )
        for l in leases
    ]


async def _outstanding_invoices(
    db: AsyncSession, customer_id: uuid.UUID | None, organization_id: uuid.UUID | None
) -> list[CustomerInvoice]:
    """Finalized invoices with money still owed, oldest first."""
    if not customer_id:
        return []
    invoices = (
        (
            await db.execute(
                select(CustomerInvoice)
                .where(
                    CustomerInvoice.customer_id == customer_id,
                    CustomerInvoice.organization_id == organization_id,
                    CustomerInvoice.status == "finalized",
                )
                .options(selectinload(CustomerInvoice.receipts))
                .order_by(CustomerInvoice.due_date, CustomerInvoice.invoice_date)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return [i for i in invoices if ar_service.balance_due(i) > 0]


async def _balance_summary(
    db: AsyncSession,
    account: ClientPortalAccount,
    resident_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> BalanceSummary:
    leases = await _load_resident_leases(db, resident_id)
    active = next(
        (l for l in leases if l.status in ("pending", "active")),
        leases[0] if leases else None,
    )
    outstanding = await _outstanding_invoices(db, customer_id, account.organization_id)
    due = sum((ar_service.balance_due(i) for i in outstanding), Decimal("0.00"))
    return BalanceSummary(
        currency=active.currency if active else "USD",
        monthly_rent=active.rent_amount if active and active.rent_amount else Decimal("0.00"),
        security_deposit=(
            active.security_deposit if active and active.security_deposit else Decimal("0.00")
        ),
        balance_due=due,
    )


@router.get("/resident-portal/balance", response_model=BalanceSummary)
async def portal_balance(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    """Lease terms plus the resident's live outstanding receivable balance."""
    resident = await _resident_for(db, account)
    summary = await _balance_summary(db, account, resident.id, resident.customer_id)
    await db.commit()
    return summary


# ─── Resident: saved payment methods ──────────────────────────────────────────

def _payment_config(config=None, capability=None) -> PaymentConfigResponse:
    if config is None:
        from app.services.organization_integration_settings import legacy_settings
        config = legacy_settings("resident_payments")
    return PaymentConfigResponse(
        configured=bool(config.is_enabled and config.secret_api_key and config.publishable_key),
        provider=config.provider,
        publishable_key=config.publishable_key,
        plaid_ach_available=bool(capability and capability.available),
        plaid_ach_unavailable_reason=capability.reason if capability else None,
    )


def _validate_processor_token(token: str, provider: str) -> None:
    # A bare run of digits is a PAN or account number, not a processor token.
    if token.replace(" ", "").replace("-", "").isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Raw card or bank numbers are not accepted; submit a processor token.",
        )
    if provider.lower() == "stripe" and not re.fullmatch(r"pm_[A-Za-z0-9_]+", token):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stripe processor_token must be a PaymentMethod ID beginning with pm_.",
        )


@router.get("/resident-portal/payment-config", response_model=PaymentConfigResponse)
async def payment_config(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    """Return browser-safe payment configuration for the authenticated portal."""
    account.last_active_at = _now()
    from app.services import organization_integration_settings as org_settings
    config = await org_settings.resolve(db, account.organization_id, "resident_payments")
    plaid = await org_settings.resolve(db, account.organization_id, "plaid")
    capability = resident_ach_service.ach_capability(plaid, config)
    return _payment_config(config, capability)


async def _resident_ach_configs(db: AsyncSession, account: ClientPortalAccount):
    from app.services import organization_integration_settings as org_settings

    plaid = await org_settings.resolve(db, account.organization_id, "plaid")
    payments = await org_settings.resolve(db, account.organization_id, "resident_payments")
    capability = resident_ach_service.ach_capability(plaid, payments)
    if not capability.available:
        raise HTTPException(status_code=503, detail=capability.reason)
    return plaid, payments


@router.post("/resident-portal/plaid-ach/link-token", response_model=AchLinkTokenResponse)
async def create_resident_ach_link_token(
    payload: AchLinkTokenRequest,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    if not payload.consent_accepted:
        raise HTTPException(status_code=422, detail="Bank-link authorization is required.")
    resident = await _resident_for(db, account)
    plaid, _ = await _resident_ach_configs(db, account)
    result = await resident_ach_service.PlaidClient(config=plaid).create_link_token(
        client_user_id=f"resident:{resident.id}",
        client_name="Portfolio Desk Resident Payments",
        products=["auth"],
        user_email=resident.email,
        legal_name=f"{resident.first_name} {resident.last_name}".strip(),
        redirect_uri=plaid.resident_ach_redirect_uri or None,
        webhook_url=plaid.resident_ach_webhook_url or None,
    )
    return AchLinkTokenResponse(link_token=result["link_token"])


@router.post(
    "/resident-portal/plaid-ach/exchange",
    response_model=PaymentMethodResponse,
    status_code=status.HTTP_201_CREATED,
)
async def exchange_resident_ach(
    payload: AchExchangeRequest,
    request: Request,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    if not payload.consent_accepted:
        raise HTTPException(status_code=422, detail="Bank-link authorization is required.")
    if not payload.public_token.strip() or not payload.account_id.strip():
        raise HTTPException(status_code=422, detail="Plaid public token and selected account are required.")
    resident = await _resident_for(db, account)
    plaid, payments = await _resident_ach_configs(db, account)
    existing = list((await db.execute(select(ResidentPaymentMethod).where(
        ResidentPaymentMethod.organization_id == account.organization_id,
        ResidentPaymentMethod.resident_id == resident.id,
    ))).scalars().all())
    customer_id = next((m.stripe_customer_id for m in existing if m.stripe_customer_id), None)
    try:
        customer_id, source = await resident_ach_service.exchange_and_attach(
            plaid_config=plaid,
            payment_config=payments,
            public_token=payload.public_token.strip(),
            account_id=payload.account_id.strip(),
            resident_id=resident.id,
            resident_name=f"{resident.first_name} {resident.last_name}".strip(),
            resident_email=resident.email,
            existing_customer_id=customer_id,
        )
    except Exception as exc:
        log.warning("Resident ACH setup failed for resident %s: %s", resident.id, exc.__class__.__name__)
        raise HTTPException(status_code=502, detail="The bank account could not be connected.") from exc
    make_default = payload.is_default or not existing
    if make_default:
        for saved in existing:
            saved.is_default = False
    method = ResidentPaymentMethod(
        organization_id=account.organization_id,
        resident_id=resident.id,
        processor="stripe",
        processor_token=source["id"],
        method_type="ach",
        status=(
            "failed"
            if source.get("status") in {"verification_failed", "errored"}
            else "active"
        ),
        stripe_customer_id=customer_id,
        bank_name=(source.get("bank_name") or payload.institution_name or "Bank")[:120],
        account_type=(source.get("account_holder_type") or "checking")[:40],
        brand=None,
        last4=str(source.get("last4") or "")[-4:] or None,
        is_default=make_default,
        consent_version=resident_ach_service.ACH_CONSENT_VERSION,
        consent_text=resident_ach_service.ACH_CONSENT_TEXT,
        consented_at=_now(),
        consent_ip=request.client.host if request.client else None,
        consent_user_agent=(request.headers.get("user-agent") or "")[:500] or None,
    )
    db.add(method)
    await db.commit()
    await db.refresh(method)
    return PaymentMethodResponse.model_validate(method)

async def _get_payment_method(
    db: AsyncSession, account: ClientPortalAccount, method_id: uuid.UUID
) -> ResidentPaymentMethod:
    """Load a saved method, scoped to the authenticated resident and their org."""
    method = (
        await db.execute(
            select(ResidentPaymentMethod).where(
                ResidentPaymentMethod.id == method_id,
                ResidentPaymentMethod.resident_id == account.entity_id,
                ResidentPaymentMethod.organization_id == account.organization_id,
            )
        )
    ).scalar_one_or_none()
    if method is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found"
        )
    return method


@router.get("/resident-portal/payment-methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    methods = (
        (
            await db.execute(
                select(ResidentPaymentMethod)
                .where(
                    ResidentPaymentMethod.resident_id == account.entity_id,
                    ResidentPaymentMethod.organization_id == account.organization_id,
                )
                .order_by(
                    ResidentPaymentMethod.is_default.desc(),
                    ResidentPaymentMethod.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    await db.commit()
    return [PaymentMethodResponse.model_validate(m) for m in methods]


@router.post(
    "/resident-portal/payment-methods",
    response_model=PaymentMethodResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment_method(
    payload: PaymentMethodCreate,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    """Save an opaque processor token. Raw card/bank numbers are never accepted."""
    token = (payload.processor_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A processor_token is required.",
        )
    from app.services import organization_integration_settings as org_settings
    payment_config = await org_settings.resolve(
        db, account.organization_id, "resident_payments"
    )
    if not payment_config.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online payments are not enabled for this organization.",
        )
    provider = payment_config.provider
    _validate_processor_token(token, provider)
    last4 = (payload.last4 or "").strip()[-4:] or None

    existing = (
        (
            await db.execute(
                select(ResidentPaymentMethod).where(
                    ResidentPaymentMethod.resident_id == account.entity_id,
                    ResidentPaymentMethod.organization_id == account.organization_id,
                )
            )
        )
        .scalars()
        .all()
    )
    make_default = payload.is_default or not existing
    if make_default:
        for m in existing:
            m.is_default = False

    method = ResidentPaymentMethod(
        organization_id=account.organization_id,
        resident_id=account.entity_id,
        processor=provider,
        processor_token=token,
        brand=payload.brand,
        last4=last4,
        exp_month=payload.exp_month,
        exp_year=payload.exp_year,
        is_default=make_default,
    )
    db.add(method)
    account.last_active_at = _now()
    await db.commit()
    await db.refresh(method)
    return PaymentMethodResponse.model_validate(method)


@router.delete(
    "/resident-portal/payment-methods/{method_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_payment_method(
    method_id: uuid.UUID,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    method = await _get_payment_method(db, account, method_id)
    # Autopay cannot point at a method that no longer exists.
    leases = await _load_resident_leases(db, account.entity_id)
    for lease in leases:
        if lease.autopay_payment_method_id == method.id:
            lease.autopay_payment_method_id = None
            lease.autopay_enabled = False
    if method.method_type == "ach" and method.stripe_customer_id:
        from app.services import organization_integration_settings as org_settings
        payments = await org_settings.resolve(db, account.organization_id, "resident_payments")
        try:
            await resident_ach_service.detach_bank_source(
                payments,
                customer_id=method.stripe_customer_id,
                source_id=method.processor_token,
            )
        except resident_ach_service.ResidentAchError:
            log.warning("Stripe bank source detach failed for method %s", method.id)
    await db.delete(method)
    account.last_active_at = _now()
    await db.commit()
    return None


# ─── Resident: payments ───────────────────────────────────────────────────────

def _payment_idempotency_key(
    resident_id: uuid.UUID,
    amount: Decimal,
    plan: list[tuple[uuid.UUID, Decimal]],
    client_key: str | None,
) -> str:
    """Stable key for one payment attempt so a retry cannot charge twice.

    Prefers the client's key. Without one, derives a digest from the resident,
    the amount and the exact invoice allocation, which collapses a double-submit
    because the second request produces an identical plan.
    """
    if client_key:
        return f"resident-payment:{resident_id}:{client_key}"
    material = f"{resident_id}|{amount}|" + "|".join(f"{i}:{p}" for i, p in plan)
    return f"resident-payment:{resident_id}:{hashlib.sha256(material.encode()).hexdigest()}"


@router.post("/resident-portal/payments", response_model=PortalPaymentResponse)
async def make_payment(
    payload: PortalPaymentCreate,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    """Pay down the authenticated resident's own outstanding balance."""
    resident = await _resident_for(db, account)
    resident_id = resident.id
    customer_id = resident.customer_id
    resident_name = f"{resident.first_name} {resident.last_name}".strip()
    amount = Decimal(str(payload.amount or 0)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payment amount must be greater than zero.",
        )
    outstanding = await _outstanding_invoices(db, customer_id, account.organization_id)
    total_due = sum((ar_service.balance_due(i) for i in outstanding), Decimal("0.00"))
    if total_due <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You have no balance due."
        )
    if amount > total_due:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Payment exceeds your outstanding balance of {total_due}.",
        )

    payment_token = None
    method = None
    if payload.payment_method_id is not None:
        method = await _get_payment_method(db, account, payload.payment_method_id)
        if method.status != "active":
            raise HTTPException(status_code=409, detail="The selected payment method is not active.")
        payment_token = method.processor_token
    if method is None:
        raise HTTPException(status_code=422, detail="A saved payment method is required.")
    payment_type = method.method_type

    # Allocate oldest invoice first, resolved before any write so a later commit
    # cannot expire the invoices this plan was built from.
    plan: list[tuple[uuid.UUID, Decimal]] = []
    remaining = amount
    for invoice in outstanding:
        if remaining <= 0:
            break
        due = ar_service.balance_due(invoice)
        portion = due if due < remaining else remaining
        if portion > 0:
            plan.append((invoice.id, portion))
            remaining -= portion

    # One charge for the whole payment, keyed so a retry settles onto the same
    # transaction instead of taking the money twice. The client sends a stable
    # key per attempt; the fallback derives one from the facts of this request
    # so a double-submit is still collapsed even from an older client.
    from app.services import organization_integration_settings as org_settings
    payment_config = await org_settings.resolve(
        db, account.organization_id, "resident_payments"
    )
    if payload.payment_method_id is not None and method.processor != payment_config.provider:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The saved payment method belongs to a different payment provider. Add a new payment method.",
        )
    key = _payment_idempotency_key(resident_id, amount, plan, payload.idempotency_key)
    attempt = None
    if payment_type == "ach":
        attempt = (await db.execute(select(ResidentPaymentAttempt).where(
            ResidentPaymentAttempt.organization_id == account.organization_id,
            ResidentPaymentAttempt.idempotency_key == key,
        ))).scalar_one_or_none()
        if attempt is not None:
            if attempt.status in {"failed", "returned"}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This bank payment attempt cannot be retried. Start a new payment.",
                )
            summary = await _balance_summary(db, account, resident_id, customer_id)
            succeeded = attempt.status == "succeeded"
            return PortalPaymentResponse(
                amount_applied=attempt.amount if succeeded else Decimal("0.00"),
                captured=succeeded,
                processor_status=attempt.status,
                detail=(
                    "Bank payment settled."
                    if succeeded
                    else "Bank payment submitted. Your balance will update after settlement."
                ),
                receipt_ids=[attempt.receipt_id] if attempt.receipt_id else [],
                balance=summary,
                attempt_id=attempt.id,
            )
        resident_leases = await _load_resident_leases(db, resident_id)
        attempt = ResidentPaymentAttempt(
            id=uuid.uuid4(),
            organization_id=account.organization_id,
            resident_id=resident_id,
            lease_id=resident_leases[0].id if resident_leases else None,
            invoice_id=plan[0][0] if plan else None,
            payment_method_id=method.id,
            amount=amount,
            method_type="ach",
            idempotency_key=key,
            status="processing",
            allocation_json=[
                {"invoice_id": str(invoice_id), "amount": str(portion)}
                for invoice_id, portion in plan
            ],
        )
        db.add(attempt)
        await db.commit()
    charge = await payment_processor.charge_payment(
        amount,
        method=payment_type,
        payment_token=payment_token,
        stripe_customer_id=method.stripe_customer_id,
        description=f"Resident payment for {resident_name}",
        idempotency_key=key,
        metadata=(
            {"resident_payment_attempt_id": str(attempt.id)}
            if attempt is not None
            else None
        ),
        config=payment_config,
    )
    if charge.status == "failed":
        if attempt is not None:
            attempt.status = "failed"
            attempt.failure_detail = charge.detail
            attempt.failed_at = _now()
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=charge.detail or "Your payment could not be processed.",
        )

    if payment_type == "ach":
        attempt = (await db.execute(
            select(ResidentPaymentAttempt)
            .where(ResidentPaymentAttempt.id == attempt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )).scalar_one()
        attempt.processor_ref = attempt.processor_ref or charge.processor_ref
        if charge.status == "succeeded":
            await resident_ach_service.settle_attempt(db, attempt)
        elif charge.status != "processing":
            attempt.status = "failed"
            attempt.failure_detail = charge.detail or "The bank payment was not accepted."
            attempt.failed_at = _now()
        await db.commit()
        summary = await _balance_summary(db, account, resident_id, customer_id)
        succeeded = attempt.status == "succeeded"
        return PortalPaymentResponse(
            amount_applied=amount if succeeded else Decimal("0.00"),
            captured=succeeded,
            processor_status=attempt.status,
            detail=(
                "Bank payment settled."
                if succeeded
                else "Bank payment submitted. Your balance will update after settlement."
            ),
            receipt_ids=[attempt.receipt_id] if attempt.receipt_id else [],
            balance=summary,
            attempt_id=attempt.id,
        )

    # Record through the shared rent path so the GL, AR aging and receipt history
    # stay identical to a staff-recorded payment.
    receipt_ids: list[uuid.UUID] = []
    applied = Decimal("0.00")
    for invoice_id, portion in plan:
        invoice = (
            await db.execute(
                select(CustomerInvoice)
                .where(
                    CustomerInvoice.id == invoice_id,
                    CustomerInvoice.organization_id == account.organization_id,
                )
                .options(selectinload(CustomerInvoice.receipts))
            )
        ).scalar_one_or_none()
        if invoice is None:
            continue
        try:
            result = await rent_svc.record_rent_payment(
                db,
                account.organization_id,
                invoice,
                portion,
                method=payment_type,
                receipt_date=date.today(),
                reference=charge.processor_ref,
            )
        except RentError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        receipt_ids.append(result["receipt"].id)
        applied += portion

    summary = await _balance_summary(db, account, resident_id, customer_id)
    response = PortalPaymentResponse(
        amount_applied=applied,
        captured=charge.captured,
        processor_status=charge.status,
        detail=charge.detail,
        receipt_ids=receipt_ids,
        balance=summary,
    )

    # Best-effort activity marker; the payment above is already committed.
    try:
        await db.execute(
            update(ClientPortalAccount)
            .where(ClientPortalAccount.id == account.id)
            .values(last_active_at=_now())
        )
        await db.commit()
    except Exception:
        log.exception("Failed to stamp portal activity after payment")
        try:
            await db.rollback()
        except Exception:
            pass
    return response


# ─── Resident: autopay ────────────────────────────────────────────────────────

@router.put("/resident-portal/autopay", response_model=AutopayResponse)
async def update_autopay(
    payload: AutopayUpdate,
    request: Request,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable autopay on one of the resident's own leases."""
    leases = await _load_resident_leases(db, account.entity_id)
    if not leases:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No lease on file."
        )
    if payload.lease_id is not None:
        lease = next((l for l in leases if l.id == payload.lease_id), None)
        if lease is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found."
            )
    else:
        lease = next(
            (l for l in leases if l.status in ("pending", "active")), leases[0]
        )

    if payload.enabled:
        if payload.payment_method_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A saved payment method is required to enable autopay.",
            )
        method = await _get_payment_method(db, account, payload.payment_method_id)
        if method.status != "active":
            raise HTTPException(status_code=409, detail="The selected payment method is not active.")
        if method.method_type != "ach":
            raise HTTPException(
                status_code=422,
                detail="Scheduled autopay currently requires a connected bank account.",
            )
        if method.method_type == "ach" and not payload.recurring_consent_accepted:
            raise HTTPException(status_code=422, detail="Recurring ACH authorization is required.")
        lease.autopay_payment_method_id = method.id
        lease.autopay_enabled = True
        if method.method_type == "ach":
            lease.autopay_consent_version = resident_ach_service.AUTOPAY_CONSENT_VERSION
            lease.autopay_consent_text = resident_ach_service.AUTOPAY_CONSENT_TEXT
            lease.autopay_consented_at = _now()
            lease.autopay_consent_ip = request.client.host if request.client else None
            lease.autopay_consent_user_agent = (
                request.headers.get("user-agent") or ""
            )[:500] or None
    else:
        lease.autopay_enabled = False
        lease.autopay_payment_method_id = None

    account.last_active_at = _now()
    await db.commit()
    return AutopayResponse(
        lease_id=lease.id,
        autopay_enabled=lease.autopay_enabled,
        autopay_payment_method_id=lease.autopay_payment_method_id,
    )


# ─── Resident: maintenance requests ───────────────────────────────────────────

async def _get_or_create_request_category(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> TicketCategory:
    existing = (
        await db.execute(
            select(TicketCategory).where(
                TicketCategory.organization_id == organization_id,
                TicketCategory.name == _RESIDENT_REQUEST_CATEGORY,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    category = TicketCategory(
        organization_id=organization_id, name=_RESIDENT_REQUEST_CATEGORY
    )
    db.add(category)
    await db.flush()
    return category


@router.post(
    "/resident-portal/maintenance-requests",
    response_model=PortalTicket,
    status_code=status.HTTP_201_CREATED,
)
async def submit_maintenance_request(
    payload: MaintenanceRequestCreate,
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    from app.services.pm_service import _pick_creator_id

    resident = await _resident_for(db, account)
    if payload.priority not in ("low", "medium", "high"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid priority")

    leases = await _load_resident_leases(db, resident.id)
    office_id = next(
        (l.unit.office_id for l in leases if l.unit and l.unit.office_id is not None),
        None,
    )
    if office_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No property is associated with your lease; please contact management.",
        )

    creator_id = await _pick_creator_id(db, account.organization_id)
    if creator_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maintenance requests are temporarily unavailable; please contact management.",
        )
    category = await _get_or_create_request_category(db, account.organization_id)

    ticket = MaintenanceTicket(
        organization_id=account.organization_id,
        subject=payload.subject[:255],
        description=payload.description,
        priority=payload.priority,
        status="open",
        category_id=category.id,
        office_id=office_id,
        created_by_id=creator_id,
        submitted_by_resident_id=resident.id,
    )
    db.add(ticket)
    account.last_active_at = _now()
    await db.commit()
    await db.refresh(ticket)
    return PortalTicket.model_validate(ticket)


@router.get("/resident-portal/maintenance-requests", response_model=list[PortalTicket])
async def list_maintenance_requests(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    tickets = (
        await db.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.submitted_by_resident_id == account.entity_id,
                MaintenanceTicket.is_deleted.is_(False),
            )
            .order_by(MaintenanceTicket.created_at.desc())
        )
    ).scalars().all()
    await db.commit()
    return [PortalTicket.model_validate(t) for t in tickets]


# ─── Resident: documents ──────────────────────────────────────────────────────

@router.get("/resident-portal/documents", response_model=list[AttachmentResponse])
async def list_documents(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    attachments = (
        await db.execute(
            select(Attachment)
            .where(
                Attachment.entity_type == _RESIDENT_ENTITY_TYPE,
                Attachment.entity_id == account.entity_id,
            )
            .order_by(Attachment.created_at.desc())
        )
    ).scalars().all()
    await db.commit()
    return [AttachmentResponse.model_validate(a) for a in attachments]


# ─── Resident: announcements ──────────────────────────────────────────────────

@router.get("/resident-portal/announcements", response_model=list[PortalAnnouncement])
async def list_announcements(
    account: ClientPortalAccount = Depends(get_resident_account),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Announcement, AnnouncementRecipient.read_at)
            .join(
                AnnouncementRecipient,
                AnnouncementRecipient.announcement_id == Announcement.id,
            )
            .where(AnnouncementRecipient.resident_id == account.entity_id)
            .order_by(Announcement.sent_at.desc())
        )
    ).all()
    await db.commit()
    return [
        PortalAnnouncement(
            id=a.id,
            title=a.title,
            body=a.body,
            sent_at=a.sent_at,
            read_at=read_at,
        )
        for a, read_at in rows
    ]

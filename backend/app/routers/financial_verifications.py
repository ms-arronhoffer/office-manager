"""Applicant financial verification staff, public-session, and webhook APIs."""
from __future__ import annotations

import hashlib
import html
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.auth.portal_sessions import PortalExchangeRequest, set_portal_cookie
from app.config import settings
from app.database import async_session, get_db
from app.models.email import EmailLog
from app.models.financial_verification import ApplicantFinancialVerification, FinancialVerificationWebhookEvent
from app.models.leasing_funnel import RentalApplication
from app.models.organization import Organization
from app.models.user import User
from app.services import financial_verification_service as svc
from app.services import organization_integration_settings as org_settings
from app.services.bank_feed.plaid_client import PlaidApiError, PlaidClient, is_configured
from app.utils.crypto import encrypt_secret
from app.utils.crypto import decrypt_secret
from app.utils.email_client import EmailCategory, send_email
from app.utils.rls import set_session_org, set_system_bypass

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()
Editor = require_role("admin", "editor")
_COOKIE = "om_financial_verify"
_COOKIE_PATH = "/api/v1/leasing-funnel/financial-verification-session"
_ELIGIBLE = {"submitted", "signed", "in_review", "screening"}


class ConsentInput(BaseModel):
    accepted: bool


class PublicTokenInput(BaseModel):
    public_token: str
    institution_name: str | None = None


class FinancialVerificationCapabilityOut(BaseModel):
    available: bool
    plaid_configured: bool
    applicant_verification_enabled: bool
    source: str
    detail: str


class FinancialVerificationOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    status: str
    expires_at: datetime
    sent_at: datetime | None
    viewed_at: datetime | None
    consented_at: datetime | None
    linked_at: datetime | None
    completed_at: datetime | None
    institution_name: str | None
    account_count: int | None
    identity_match: bool | None
    ownership_match: bool | None
    available_balance_total: Decimal | None
    current_balance_total: Decimal | None
    recurring_income_monthly: Decimal | None
    income_months_observed: int | None
    recommendation: str
    reason_codes: list[str]
    last_error: str | None
    decision_support_disclaimer: str = "This result supports staff review only and must not automatically approve or deny an applicant."


def _staff_out(row: ApplicantFinancialVerification) -> dict:
    return {
        "id": row.id, "application_id": row.application_id, "status": row.status,
        "expires_at": row.expires_at, "sent_at": row.sent_at, "viewed_at": row.viewed_at,
        "consented_at": row.consented_at, "linked_at": row.linked_at,
        "completed_at": row.completed_at, "institution_name": row.institution_name,
        "account_count": row.account_count, "identity_match": row.identity_match,
        "ownership_match": row.ownership_match,
        "available_balance_total": row.available_balance_total,
        "current_balance_total": row.current_balance_total,
        "recurring_income_monthly": row.recurring_income_monthly,
        "income_months_observed": row.income_months_observed,
        "recommendation": row.recommendation,
        "reason_codes": (row.summary_json or {}).get("reason_codes", []),
        "last_error": row.last_error,
    }


async def _staff_application(db: AsyncSession, app_id: uuid.UUID, org_id: uuid.UUID) -> RentalApplication:
    row = (await db.execute(select(RentalApplication).where(
        RentalApplication.id == app_id,
        RentalApplication.organization_id == org_id,
        RentalApplication.is_deleted.is_(False),
    ))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Application not found.")
    return row


async def _staff_verification(db: AsyncSession, verification_id: uuid.UUID, org_id: uuid.UUID) -> ApplicantFinancialVerification:
    row = (await db.execute(select(ApplicantFinancialVerification).where(
        ApplicantFinancialVerification.id == verification_id,
        ApplicantFinancialVerification.organization_id == org_id,
    ))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Financial verification not found.")
    return row


async def _public_lookup(db: AsyncSession, token: str) -> ApplicantFinancialVerification:
    await set_system_bypass(db)
    row = (await db.execute(
        select(ApplicantFinancialVerification)
        .options(selectinload(ApplicantFinancialVerification.application).selectinload(RentalApplication.unit))
        .where(ApplicantFinancialVerification.invitation_token_hash == svc.hash_invitation_token(token))
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Financial verification request not found.")
    await set_session_org(db, row.organization_id)
    if row.expires_at <= svc.now() and row.status not in {"completed", "declined", "revoked"}:
        row.status = "expired"
        await db.commit()
    return row


def _public_view(row: ApplicantFinancialVerification, org_name: str) -> dict:
    application = row.application
    unit = application.unit
    return {
        "applicant_first_name": application.applicant_first_name,
        "organization_name": org_name,
        "property_unit_label": (unit.name or f"Unit {unit.unit_number}") if unit else None,
        "status": row.status,
        "expires_at": row.expires_at,
        "disclosure_text": svc.CONSENT_TEXT,
        "consent_version": svc.CONSENT_VERSION,
        "requested_checks": svc.REQUESTED_CHECKS,
        "consent_required": row.consented_at is None,
    }


async def _org_name(db: AsyncSession, org_id: uuid.UUID) -> str:
    return (await db.execute(select(Organization.name).where(Organization.id == org_id))).scalar_one()


async def _deliver_email(*, org_id: uuid.UUID, verification_id: uuid.UUID, recipient: str, applicant_name: str, org_name: str, raw_token: str) -> None:
    subject = f"{org_name} requests financial verification"
    link = f"{settings.FRONTEND_URL.rstrip('/')}/financial-verify/{raw_token}"
    body = (
        f"<p>Hello {html.escape(applicant_name)},</p>"
        f"<p>{html.escape(org_name)} requests a financial verification for your rental application.</p>"
        "<p>You control whether to consent. Your bank credentials are entered only in Plaid and are not shared with Portfolio Desk or the requesting organization.</p>"
        f"<p><a href=\"{html.escape(link)}\">Review and choose whether to continue</a></p>"
        "<p>This request expires in 7 days.</p>"
    )
    sent, error = False, None
    try:
        sent = bool(await send_email(recipient, subject, body, category=EmailCategory.NOTIFICATIONS))
        if not sent:
            error = "Email provider did not accept the message."
    except Exception as exc:  # pragma: no cover
        error = str(exc)
        logger.exception("Financial verification email failed for verification %s", verification_id)
    async with async_session() as db:
        db.add(EmailLog(rule_id=None, sent_to=recipient, subject=subject, body=error, status="sent" if sent else "failed"))
        await db.commit()


def _queue_email(background: BackgroundTasks, row: ApplicantFinancialVerification, application: RentalApplication, org_name: str, raw_token: str) -> None:
    background.add_task(_deliver_email, org_id=row.organization_id, verification_id=row.id,
        recipient=application.applicant_email,
        applicant_name=f"{application.applicant_first_name} {application.applicant_last_name}".strip(),
        org_name=org_name, raw_token=raw_token)


@router.get("/financial-verifications/capability", response_model=FinancialVerificationCapabilityOut)
async def financial_verification_capability(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = await org_settings.resolve(db, current_user.organization_id, "plaid")
    plaid_configured = is_configured(config)
    enabled = bool(config.applicant_verification_enabled)
    if not plaid_configured:
        detail = "Plaid is not configured for this organization. An administrator must configure it under Finance > Connections."
    elif not enabled:
        detail = "Plaid is configured, but applicant financial verification is disabled. An administrator must enable it under Finance > Connections."
    else:
        detail = "Plaid applicant financial verification is ready."
    return FinancialVerificationCapabilityOut(
        available=plaid_configured and enabled,
        plaid_configured=plaid_configured,
        applicant_verification_enabled=enabled,
        source=config.source,
        detail=detail,
    )


@router.post("/applications/{app_id}/financial-verifications", response_model=FinancialVerificationOut, status_code=201)
async def create_verification(app_id: uuid.UUID, background: BackgroundTasks, db: AsyncSession = Depends(get_db), current_user: User = Depends(Editor)):
    application = await _staff_application(db, app_id, current_user.organization_id)
    if application.status not in _ELIGIBLE:
        raise HTTPException(409, "Financial verification is available after an application is submitted or signed and before decision.")
    config = await org_settings.resolve(db, current_user.organization_id, "plaid")
    if not is_configured(config) or not config.applicant_verification_enabled:
        raise HTTPException(503, "Plaid applicant financial verification is not enabled for this organization.")
    active = (await db.execute(select(ApplicantFinancialVerification).where(
        ApplicantFinancialVerification.application_id == app_id,
        ApplicantFinancialVerification.status.in_(["invited", "viewed", "consented", "linking", "processing", "action_required"]),
    ))).scalar_one_or_none()
    if active:
        raise HTTPException(409, "An active financial verification already exists.")
    raw_token = svc.generate_invitation_token()
    row = ApplicantFinancialVerification(organization_id=current_user.organization_id, application_id=app_id,
        invitation_token_hash=svc.hash_invitation_token(raw_token), expires_at=svc.now() + timedelta(days=7), sent_at=svc.now())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    _queue_email(background, row, application, await _org_name(db, current_user.organization_id), raw_token)
    return _staff_out(row)


@router.get("/applications/{app_id}/financial-verifications", response_model=list[FinancialVerificationOut])
async def list_verifications(app_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    await _staff_application(db, app_id, current_user.organization_id)
    rows = (await db.execute(select(ApplicantFinancialVerification).where(
        ApplicantFinancialVerification.application_id == app_id,
        ApplicantFinancialVerification.organization_id == current_user.organization_id,
    ).order_by(ApplicantFinancialVerification.created_at.desc()))).scalars().all()
    return [_staff_out(row) for row in rows]


@router.post("/financial-verifications/{verification_id}/resend", response_model=FinancialVerificationOut)
async def resend_verification(verification_id: uuid.UUID, background: BackgroundTasks, db: AsyncSession = Depends(get_db), current_user: User = Depends(Editor)):
    row = await _staff_verification(db, verification_id, current_user.organization_id)
    if row.status in {"completed", "declined", "revoked", "processing"}:
        raise HTTPException(409, "This request cannot be resent.")
    raw_token = svc.generate_invitation_token()
    row.invitation_token_hash = svc.hash_invitation_token(raw_token)
    row.status, row.expires_at, row.sent_at = "invited", svc.now() + timedelta(days=7), svc.now()
    await db.commit()
    application = await _staff_application(db, row.application_id, current_user.organization_id)
    _queue_email(background, row, application, await _org_name(db, current_user.organization_id), raw_token)
    return _staff_out(row)


@router.post("/financial-verifications/{verification_id}/cancel", response_model=FinancialVerificationOut)
async def cancel_verification(verification_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(Editor)):
    row = await _staff_verification(db, verification_id, current_user.organization_id)
    if row.status == "completed":
        raise HTTPException(409, "A completed request cannot be cancelled.")
    if row.access_token_encrypted:
        config = await org_settings.resolve(db, row.organization_id, "plaid")
        try:
            await PlaidClient(config=config).remove_item(decrypt_secret(row.access_token_encrypted))
        except (PlaidApiError, ValueError):
            logger.warning("Could not remove Plaid Item while cancelling verification %s", row.id)
    row.status = "revoked"
    row.access_token_encrypted = None
    row.disconnected_at = svc.now()
    await db.commit()
    return _staff_out(row)


@public_router.post("/financial-verifications/exchange-session", status_code=204)
async def exchange_session(payload: PortalExchangeRequest, response: Response, db: AsyncSession = Depends(get_db)):
    row = await _public_lookup(db, payload.token)
    if row.status in {"expired", "declined", "revoked"}:
        raise HTTPException(410, "This financial verification link is no longer active.")
    max_age = max(1, int((row.expires_at - svc.now()).total_seconds()))
    set_portal_cookie(response, _COOKIE, payload.token, _COOKIE_PATH, max_age)


async def _session_token(cookie: str | None) -> str:
    if not cookie:
        raise HTTPException(401, "Financial verification session required.")
    return cookie


@public_router.get("/financial-verifications/{token}")
async def public_view(token: str, db: AsyncSession = Depends(get_db)):
    row = await _public_lookup(db, token)
    if row.status == "invited":
        row.status, row.viewed_at = "viewed", svc.now()
        await db.commit()
    return _public_view(row, await _org_name(db, row.organization_id))


@public_router.get("/financial-verification-session")
async def public_view_session(cookie: str | None = Cookie(None, alias=_COOKIE), db: AsyncSession = Depends(get_db)):
    return await public_view(await _session_token(cookie), db)


async def _consent(token: str, payload: ConsentInput, request: Request, user_agent: str | None, db: AsyncSession) -> dict:
    row = await _public_lookup(db, token)
    if row.status in {"expired", "declined", "revoked", "completed"}:
        raise HTTPException(410, "This financial verification request is not active.")
    if not payload.accepted:
        raise HTTPException(422, "Explicit consent is required before connecting a bank account.")
    row.status, row.consented_at = "consented", svc.now()
    row.consent_text, row.consent_version = svc.CONSENT_TEXT, svc.CONSENT_VERSION
    row.consent_ip = request.client.host if request.client else None
    row.consent_user_agent = user_agent
    config = await org_settings.resolve(db, row.organization_id, "plaid")
    if not is_configured(config) or not config.applicant_verification_enabled:
        raise HTTPException(503, "Financial verification is not currently available.")
    application = row.application
    try:
        result = await PlaidClient(config=config).create_link_token(
            client_user_id=str(application.id), client_name=await _org_name(db, row.organization_id),
            products=["identity", "auth", "transactions"], webhook_url=config.webhook_url or None,
            user_email=application.applicant_email,
            legal_name=f"{application.applicant_first_name} {application.applicant_last_name}".strip(),
        )
    except PlaidApiError as exc:
        row.status, row.last_error = "error", exc.error_code or "plaid_link_token_error"
        await db.commit()
        raise HTTPException(502, "Plaid could not start the secure bank connection.") from exc
    row.status = "linking"
    await db.commit()
    return {"link_token": result["link_token"], "status": row.status}


@public_router.post("/financial-verifications/{token}/consent")
async def consent(token: str, payload: ConsentInput, request: Request, user_agent: str | None = Header(None, alias="User-Agent"), db: AsyncSession = Depends(get_db)):
    return await _consent(token, payload, request, user_agent, db)


@public_router.post("/financial-verification-session/consent")
async def consent_session(payload: ConsentInput, request: Request, cookie: str | None = Cookie(None, alias=_COOKIE), user_agent: str | None = Header(None, alias="User-Agent"), db: AsyncSession = Depends(get_db)):
    return await _consent(await _session_token(cookie), payload, request, user_agent, db)


async def _exchange(token: str, payload: PublicTokenInput, db: AsyncSession) -> dict:
    row = await _public_lookup(db, token)
    if not row.consented_at or row.status != "linking":
        raise HTTPException(409, "Consent is required before Plaid Link exchange.")
    config = await org_settings.resolve(db, row.organization_id, "plaid")
    client = PlaidClient(config=config)
    try:
        exchanged = await client.exchange_public_token(payload.public_token)
        row.access_token_encrypted = encrypt_secret(exchanged["access_token"])
        row.item_id = exchanged["item_id"]
        row.institution_name = payload.institution_name[:255] if payload.institution_name else None
        row.linked_at, row.status = svc.now(), "processing"
        await db.flush()
        await svc.process_verification(row, row.application, client)
    except (PlaidApiError, KeyError, ValueError, RuntimeError) as exc:
        row.status, row.last_error = "error", getattr(exc, "error_code", None) or type(exc).__name__
        row.access_token_encrypted = None
        await db.commit()
        raise HTTPException(502, "Financial verification could not be completed. Please contact the requesting organization.") from exc
    await db.commit()
    return {"status": row.status, "message": "Financial verification is complete."}


@public_router.post("/financial-verifications/{token}/exchange")
async def exchange(token: str, payload: PublicTokenInput, db: AsyncSession = Depends(get_db)):
    return await _exchange(token, payload, db)


@public_router.post("/financial-verification-session/exchange")
async def exchange_session_token(payload: PublicTokenInput, cookie: str | None = Cookie(None, alias=_COOKIE), db: AsyncSession = Depends(get_db)):
    return await _exchange(await _session_token(cookie), payload, db)


def _status(row: ApplicantFinancialVerification) -> dict:
    messages = {"completed": "Your financial verification is complete.", "action_required": "Your bank connection needs attention. Please contact the requesting organization.", "error": "The verification could not be completed. Please contact the requesting organization.", "declined": "You declined this request.", "expired": "This request has expired.", "revoked": "This request was cancelled."}
    return {"status": row.status, "message": messages.get(row.status, "Your financial verification is in progress.")}


@public_router.get("/financial-verifications/{token}/status")
async def verification_status(token: str, db: AsyncSession = Depends(get_db)):
    return _status(await _public_lookup(db, token))


@public_router.get("/financial-verification-session/status")
async def verification_status_session(cookie: str | None = Cookie(None, alias=_COOKIE), db: AsyncSession = Depends(get_db)):
    return _status(await _public_lookup(db, await _session_token(cookie)))


@public_router.post("/financial-verifications/{token}/decline")
async def decline(token: str, db: AsyncSession = Depends(get_db)):
    row = await _public_lookup(db, token)
    if row.status == "completed":
        raise HTTPException(409, "This verification is already complete.")
    if row.access_token_encrypted:
        config = await org_settings.resolve(db, row.organization_id, "plaid")
        try:
            await PlaidClient(config=config).remove_item(decrypt_secret(row.access_token_encrypted))
        except (PlaidApiError, ValueError):
            logger.warning("Could not remove Plaid Item after applicant declined verification %s", row.id)
    row.status, row.access_token_encrypted = "declined", None
    row.disconnected_at = svc.now()
    await db.commit()
    return _status(row)


@public_router.post("/financial-verification-session/decline")
async def decline_session(cookie: str | None = Cookie(None, alias=_COOKIE), db: AsyncSession = Depends(get_db)):
    return await decline(await _session_token(cookie), db)


@public_router.post("/plaid/webhook", status_code=204)
async def plaid_webhook(request: Request, verification: str | None = Header(None, alias="X-Plaid-Verification"), db: AsyncSession = Depends(get_db)):
    body = await request.body()
    try:
        untrusted = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "Invalid webhook body.") from exc
    item_id = untrusted.get("item_id")
    if not item_id:
        raise HTTPException(400, "Webhook item is required.")
    await set_system_bypass(db)
    row = (await db.execute(select(ApplicantFinancialVerification).where(ApplicantFinancialVerification.item_id == item_id))).scalar_one_or_none()
    if not row:
        return Response(status_code=204)
    await set_session_org(db, row.organization_id)
    config = await org_settings.resolve(db, row.organization_id, "plaid")
    try:
        payload = await svc.verify_webhook_jwt(body, verification or "", PlaidClient(config=config))
    except (ValueError, JWTError, PlaidApiError) as exc:
        raise HTTPException(401, "Invalid Plaid webhook signature.") from exc
    digest = hashlib.sha256(body).hexdigest()
    if (await db.execute(select(FinancialVerificationWebhookEvent.id).where(FinancialVerificationWebhookEvent.event_digest == digest))).first():
        return Response(status_code=204)
    webhook_type, code = str(payload.get("webhook_type", "UNKNOWN")), str(payload.get("webhook_code", "UNKNOWN"))
    db.add(FinancialVerificationWebhookEvent(organization_id=row.organization_id, verification_id=row.id, event_digest=digest, webhook_type=webhook_type, webhook_code=code))
    row.last_webhook_at = svc.now()
    if code in {"USER_PERMISSION_REVOKED", "USER_ACCOUNT_REVOKED"}:
        row.status, row.access_token_encrypted = "revoked", None
    elif code in {"ERROR", "ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION"}:
        row.status, row.last_error = "action_required", code
    elif code == "LOGIN_REPAIRED" and row.status == "action_required":
        row.status, row.last_error = "processing", None
    elif code in {"INITIAL_UPDATE", "SYNC_UPDATES_AVAILABLE"} and row.access_token_encrypted:
        application = (
            await db.execute(
                select(RentalApplication).where(
                    RentalApplication.id == row.application_id,
                    RentalApplication.organization_id == row.organization_id,
                )
            )
        ).scalar_one()
        await svc.process_verification(row, application, PlaidClient(config=config))
    else:
        logger.info("Unsupported Plaid financial webhook type=%s code=%s", webhook_type, code)
    await db.commit()
    return Response(status_code=204)
"""Digital Waivers API.

Two routers are exported:

* ``router`` — authenticated, ``digital_waivers``-gated endpoints for managing
  templates and sending/tracking waiver requests (mounted with the feature
  guard in ``main.py``).
* ``public_router`` — unauthenticated, token-addressed signing endpoints used by
  the recipient (including ad-hoc *visitors*). These are intentionally NOT
  feature-gated so a sent link keeps working; they are protected by the
  unguessable ``sign_token`` instead (mirroring the client/vendor portal token
  pattern).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.models.waiver import (
    WAIVER_RECIPIENT_TYPES,
    WaiverRequest,
    WaiverSignature,
    WaiverTemplate,
)
from app.seeds.waiver_seed import seed_prebuilt_templates_for_org
from app.services import waiver_service
from app.utils.email_client import send_email

router = APIRouter()
public_router = APIRouter()

_SIGN_TTL_DAYS = 30


# ── Schemas ───────────────────────────────────────────────────────────────────

class TemplateCreate(BaseModel):
    name: str
    description: str | None = None
    body: str


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    body: str | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    body: str
    is_prebuilt: bool
    prebuilt_key: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SendWaiverRequest(BaseModel):
    template_id: uuid.UUID
    recipient_type: str  # 'contact' | 'visitor'
    recipient_email: str
    recipient_name: str | None = None
    entity_contact_id: uuid.UUID | None = None


class WaiverRequestResponse(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID | None
    recipient_type: str
    recipient_name: str | None
    recipient_email: str
    entity_contact_id: uuid.UUID | None
    title: str
    status: str
    document_hash: str
    sign_url: str | None = None
    expires_at: datetime | None
    sent_at: datetime | None
    viewed_at: datetime | None
    signed_at: datetime | None
    declined_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicWaiverView(BaseModel):
    title: str
    body: str
    status: str
    recipient_name: str | None
    recipient_type: str
    organization_name: str | None
    consent_text: str
    expired: bool


class VisitorDetail(BaseModel):
    label: str
    value: str


class SignSubmission(BaseModel):
    signer_name: str
    signer_email: str | None = None
    signature_type: str = "typed"  # 'typed' | 'drawn'
    signature_data: str
    consent_agreed: bool
    visitor_details: list[VisitorDetail] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sign_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/sign/{token}"


def _request_response(req: WaiverRequest, *, include_url: bool = False) -> WaiverRequestResponse:
    data = WaiverRequestResponse.model_validate(req, from_attributes=True)
    if include_url and req.status in ("sent", "viewed"):
        data.sign_url = _sign_url(req.sign_token)
    return data


async def _load_template(db: AsyncSession, template_id: uuid.UUID, org_id) -> WaiverTemplate:
    result = await db.execute(
        select(WaiverTemplate).where(
            WaiverTemplate.id == template_id,
            WaiverTemplate.organization_id == org_id,
        )
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return tpl


async def _org_name(db: AsyncSession, org_id) -> str | None:
    if org_id is None:
        return None
    result = await db.execute(select(Organization.name).where(Organization.id == org_id))
    return result.scalar_one_or_none()


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List waiver templates, seeding the prebuilt library on first access."""
    await seed_prebuilt_templates_for_org(db, current_user.organization_id)
    await db.commit()
    result = await db.execute(
        select(WaiverTemplate)
        .where(WaiverTemplate.organization_id == current_user.organization_id)
        .order_by(WaiverTemplate.is_prebuilt.desc(), WaiverTemplate.name)
    )
    return [TemplateResponse.model_validate(t, from_attributes=True) for t in result.scalars().all()]


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    tpl = WaiverTemplate(
        organization_id=current_user.organization_id,
        name=payload.name,
        description=payload.description,
        body=payload.body,
        is_prebuilt=False,
        is_active=True,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return TemplateResponse.model_validate(tpl, from_attributes=True)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    tpl = await _load_template(db, template_id, current_user.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tpl, field, value)
    await db.commit()
    await db.refresh(tpl)
    return TemplateResponse.model_validate(tpl, from_attributes=True)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    tpl = await _load_template(db, template_id, current_user.organization_id)
    await db.delete(tpl)
    await db.commit()


# ── Sending & tracking ────────────────────────────────────────────────────────

@router.post("/send", response_model=WaiverRequestResponse, status_code=status.HTTP_201_CREATED)
async def send_waiver(
    payload: SendWaiverRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    """Render a template for a recipient and send a signing link."""
    if payload.recipient_type not in WAIVER_RECIPIENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"recipient_type must be one of {', '.join(WAIVER_RECIPIENT_TYPES)}",
        )
    tpl = await _load_template(db, payload.template_id, current_user.organization_id)
    org_name = await _org_name(db, current_user.organization_id)

    context = waiver_service.build_merge_context(
        recipient_name=payload.recipient_name, organization_name=org_name
    )
    rendered = waiver_service.render_body(tpl.body, context)
    doc_hash = waiver_service.compute_document_hash(rendered)
    token = secrets.token_hex(32)
    now = _now()

    req = WaiverRequest(
        organization_id=current_user.organization_id,
        template_id=tpl.id,
        recipient_type=payload.recipient_type,
        recipient_name=payload.recipient_name,
        recipient_email=str(payload.recipient_email),
        entity_contact_id=payload.entity_contact_id,
        title=tpl.name,
        rendered_body=rendered,
        document_hash=doc_hash,
        status="sent",
        sign_token=token,
        expires_at=now + timedelta(days=_SIGN_TTL_DAYS),
        sent_at=now,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # Best-effort email; failure to send must not roll back the created request.
    try:
        sign_url = _sign_url(token)
        html = (
            f"<p>Hello{(' ' + payload.recipient_name) if payload.recipient_name else ''},</p>"
            f"<p>{org_name or 'An organization'} has requested your signature on "
            f"<strong>{tpl.name}</strong>.</p>"
            f"<p><a href=\"{sign_url}\">Review and sign the document</a></p>"
            f"<p>This link expires on {req.expires_at:%B %d, %Y}.</p>"
        )
        await send_email(str(payload.recipient_email), f"Signature requested: {tpl.name}", html)
    except Exception:  # pragma: no cover - email best-effort
        pass

    return _request_response(req, include_url=True)


@router.get("/requests", response_model=list[WaiverRequestResponse])
async def list_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WaiverRequest)
        .where(WaiverRequest.organization_id == current_user.organization_id)
        .order_by(WaiverRequest.created_at.desc())
    )
    return [_request_response(r, include_url=True) for r in result.scalars().all()]


async def _load_request(db: AsyncSession, request_id: uuid.UUID, org_id) -> WaiverRequest:
    result = await db.execute(
        select(WaiverRequest).where(
            WaiverRequest.id == request_id,
            WaiverRequest.organization_id == org_id,
        )
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiver request not found")
    return req


@router.get("/requests/{request_id}", response_model=WaiverRequestResponse)
async def get_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = await _load_request(db, request_id, current_user.organization_id)
    return _request_response(req, include_url=True)


@router.get("/requests/{request_id}/pdf")
async def download_signed_pdf(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the signed waiver PDF (with its e-signature audit trail)."""
    req = await _load_request(db, request_id, current_user.organization_id)
    if req.status != "signed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Waiver is not signed yet")
    sig_result = await db.execute(
        select(WaiverSignature).where(WaiverSignature.request_id == req.id)
    )
    sig = sig_result.scalar_one_or_none()
    if not sig:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signature not found")

    pdf = waiver_service.generate_signed_pdf(
        title=req.title,
        body=req.rendered_body,
        document_hash=req.document_hash,
        signer_name=sig.signer_name,
        signer_email=sig.signer_email,
        signature_type=sig.signature_type,
        signature_data=sig.signature_data,
        consent_text=sig.consent_text,
        signed_at=_aware(sig.signed_at),
        ip_address=sig.ip_address,
        user_agent=sig.user_agent,
    )
    filename = f"waiver-{req.id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Public signing surface (token-addressed, unauthenticated) ─────────────────

async def _load_by_token(db: AsyncSession, token: str) -> WaiverRequest:
    result = await db.execute(select(WaiverRequest).where(WaiverRequest.sign_token == token))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waiver not found")
    return req


def _is_expired(req: WaiverRequest) -> bool:
    expires = _aware(req.expires_at)
    return bool(expires and expires < _now())


@public_router.get("/sign/{token}", response_model=PublicWaiverView)
async def public_view_waiver(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch the document for a signing link and mark it viewed."""
    req = await _load_by_token(db, token)
    expired = _is_expired(req)
    if req.status == "sent" and not expired:
        req.status = "viewed"
        req.viewed_at = _now()
        await db.commit()
        await db.refresh(req)
    elif expired and req.status in ("sent", "viewed"):
        req.status = "expired"
        await db.commit()
        await db.refresh(req)

    org_name = await _org_name(db, req.organization_id)
    return PublicWaiverView(
        title=req.title,
        body=req.rendered_body,
        status=req.status,
        recipient_name=req.recipient_name,
        recipient_type=req.recipient_type,
        organization_name=org_name,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        expired=expired,
    )


@public_router.post("/sign/{token}", response_model=PublicWaiverView)
async def public_sign_waiver(
    token: str,
    payload: SignSubmission,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_agent: str | None = Header(None, alias="User-Agent"),
):
    """Capture a signature and lock the waiver.

    Enforces ESIGN/UETA-style controls: explicit consent, attribution (signer
    name/email + IP + user-agent), a timestamp, and the document hash the signer
    agreed to — making the signed record tamper-evident and immutable.
    """
    req = await _load_by_token(db, token)
    if _is_expired(req):
        req.status = "expired"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This waiver link has expired")
    if req.status == "signed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This waiver is already signed")
    if req.status == "declined":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This waiver was declined")
    if not payload.consent_agreed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must consent to sign electronically.",
        )
    if payload.signature_type not in ("typed", "drawn"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature type")
    if not payload.signature_data.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signature is required")

    now = _now()
    signature = WaiverSignature(
        request_id=req.id,
        signer_name=payload.signer_name,
        signer_email=str(payload.signer_email) if payload.signer_email else None,
        signature_type=payload.signature_type,
        signature_data=payload.signature_data,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        consent_agreed=True,
        signed_at=now,
        ip_address=request.client.host if request.client else None,
        user_agent=(user_agent or "")[:500] or None,
        document_hash=req.document_hash,
    )
    db.add(signature)

    if payload.visitor_details:
        req.visitor_details = {d.label: d.value for d in payload.visitor_details}
    req.status = "signed"
    req.signed_at = now
    await db.commit()
    await db.refresh(req)

    org_name = await _org_name(db, req.organization_id)
    return PublicWaiverView(
        title=req.title,
        body=req.rendered_body,
        status=req.status,
        recipient_name=req.recipient_name,
        recipient_type=req.recipient_type,
        organization_name=org_name,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        expired=False,
    )


@public_router.post("/decline/{token}", response_model=PublicWaiverView)
async def public_decline_waiver(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    req = await _load_by_token(db, token)
    if req.status in ("signed", "declined"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This waiver is already {req.status}",
        )
    req.status = "declined"
    req.declined_at = _now()
    await db.commit()
    await db.refresh(req)
    org_name = await _org_name(db, req.organization_id)
    return PublicWaiverView(
        title=req.title,
        body=req.rendered_body,
        status=req.status,
        recipient_name=req.recipient_name,
        recipient_type=req.recipient_type,
        organization_name=org_name,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        expired=False,
    )

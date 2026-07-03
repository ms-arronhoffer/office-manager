"""Leasing funnel API router (Phase 2.4) — ``/api/v1/leasing-funnel``.

The top-of-funnel that feeds the resident/lease domain:

  - online rental applications (public submission + staff review workflow)
  - tenant screening via a third-party provider (pluggable, stubbed when unset)
  - full-lease e-signing that extends the waiver e-signature engine to
    multi-party lease documents

Staff endpoints on ``router`` are org-guarded and gated to ``admin``/``editor``
(destructive deletes to ``admin``). Public endpoints on ``public_router`` — the
application form and the per-party lease signing pages — are unauthenticated and
mirror the public waiver-signing surface (token-based, ESIGN/UETA controls).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.leasing_funnel import (
    APPLICATION_STATUSES,
    LEASE_PARTY_ROLES,
    LEASE_SIGNATURE_TYPES,
    LeaseSignatureParty,
    LeaseSignatureRequest,
    RentalApplication,
    ScreeningReport,
)
from app.models.organization import Organization
from app.models.lease_template import LeaseTemplate
from app.models.resident import (
    RentalUnit,
    ResidentLease,
    ResidentLeaseOccupant,
)
from app.models.user import User
from app.services import leasing_funnel_service as svc
from app.services import waiver_service
from app.services.leasing_funnel_service import FunnelError

router = APIRouter()
public_router = APIRouter()

Editor = require_role("admin", "editor")
Admin = require_role("admin")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ApplicationSubmit(BaseModel):
    organization_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    applicant_first_name: str
    applicant_last_name: str
    applicant_email: str
    applicant_phone: str | None = None
    desired_move_in: date | None = None
    monthly_income: Decimal | None = None
    application_data: dict | None = None


class ApplicationStaffCreate(BaseModel):
    unit_id: uuid.UUID | None = None
    applicant_first_name: str
    applicant_last_name: str
    applicant_email: str
    applicant_phone: str | None = None
    desired_move_in: date | None = None
    monthly_income: Decimal | None = None
    application_data: dict | None = None
    notes: str | None = None


class ApplicationUpdate(BaseModel):
    status: str | None = None
    decision_notes: str | None = None
    notes: str | None = None


class ScreeningReportResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    provider: str
    status: str
    recommendation: str
    credit_score: int | None
    external_ref: str | None
    report_data: dict | None
    requested_at: datetime | None
    completed_at: datetime | None

    class Config:
        from_attributes = True


class ApplicationResponse(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID | None
    applicant_first_name: str
    applicant_last_name: str
    applicant_email: str
    applicant_phone: str | None
    desired_move_in: date | None
    monthly_income: Decimal | None
    application_data: dict | None
    notes: str | None
    status: str
    decision_notes: str | None
    decided_at: datetime | None
    resident_id: uuid.UUID | None

    class Config:
        from_attributes = True


class PartyInput(BaseModel):
    signer_name: str
    signer_email: str
    role: str = "tenant"
    sign_order: int | None = None


class LeaseSignatureCreate(BaseModel):
    title: str
    body: str
    parties: list[PartyInput]
    resident_lease_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class LeaseSignatureFromTemplate(BaseModel):
    resident_lease_id: uuid.UUID
    template_id: uuid.UUID
    title: str | None = None
    # When omitted, the lease occupants with an email become the signing parties.
    parties: list[PartyInput] | None = None
    expires_at: datetime | None = None


class PartyResponse(BaseModel):
    id: uuid.UUID
    signer_name: str
    signer_email: str
    role: str
    sign_order: int
    status: str
    signed_at: datetime | None

    class Config:
        from_attributes = True


class LeaseSignatureResponse(BaseModel):
    id: uuid.UUID
    resident_lease_id: uuid.UUID | None
    title: str
    status: str
    document_hash: str
    expires_at: datetime | None
    sent_at: datetime | None
    completed_at: datetime | None
    parties: list[PartyResponse]

    class Config:
        from_attributes = True


class PublicLeaseView(BaseModel):
    title: str
    body: str
    request_status: str
    party_status: str
    signer_name: str
    consent_text: str
    expired: bool


class SignSubmission(BaseModel):
    signature_type: str = "typed"
    signature_data: str
    consent_agreed: bool = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_application(db: AsyncSession, app_id: uuid.UUID, org_id) -> RentalApplication:
    application = (
        await db.execute(
            select(RentalApplication).where(
                RentalApplication.id == app_id,
                RentalApplication.organization_id == org_id,
                RentalApplication.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found.")
    return application


async def _validate_unit(db: AsyncSession, unit_id: uuid.UUID, org_id) -> None:
    unit = (
        await db.execute(
            select(RentalUnit.id).where(
                RentalUnit.id == unit_id,
                RentalUnit.organization_id == org_id,
            )
        )
    ).first()
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rental unit not found.")


# ─── Applications (staff) ─────────────────────────────────────────────────────

@router.get("/applications", response_model=list[ApplicationResponse])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    unit_id: uuid.UUID | None = Query(None),
):
    stmt = select(RentalApplication).where(
        RentalApplication.organization_id == current_user.organization_id,
        RentalApplication.is_deleted.is_(False),
    )
    if status_filter is not None:
        stmt = stmt.where(RentalApplication.status == status_filter)
    if unit_id is not None:
        stmt = stmt.where(RentalApplication.unit_id == unit_id)
    apps = (
        await db.execute(stmt.order_by(RentalApplication.created_at.desc()))
    ).scalars().all()
    return apps


@router.post("/applications", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationStaffCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    if payload.unit_id is not None:
        await _validate_unit(db, payload.unit_id, current_user.organization_id)
    application = RentalApplication(
        organization_id=current_user.organization_id,
        applicant_email=str(payload.applicant_email),
        **payload.model_dump(exclude={"applicant_email"}),
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


@router.get("/applications/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_application(db, app_id, current_user.organization_id)


@router.patch("/applications/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: uuid.UUID,
    payload: ApplicationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    application = await _get_application(db, app_id, current_user.organization_id)
    data = payload.model_dump(exclude_unset=True)
    if "notes" in data:
        application.notes = data["notes"]
    if "status" in data and data["status"] is not None:
        if data["status"] not in APPLICATION_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid status.")
        try:
            await svc.set_application_status(
                db, application, data["status"],
                decided_by_id=current_user.id,
                decision_notes=data.get("decision_notes"),
            )
        except FunnelError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    elif "decision_notes" in data:
        application.decision_notes = data["decision_notes"]
    await db.commit()
    await db.refresh(application)
    return application


@router.delete("/applications/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Admin),
):
    application = await _get_application(db, app_id, current_user.organization_id)
    application.is_deleted = True
    await db.commit()


@router.post("/applications/{app_id}/screen", response_model=ScreeningReportResponse)
async def screen_application(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    application = await _get_application(db, app_id, current_user.organization_id)
    report = await svc.run_screening(db, current_user.organization_id, application)
    await db.commit()
    await db.refresh(report)
    return report


@router.get("/applications/{app_id}/screening", response_model=list[ScreeningReportResponse])
async def list_screening(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_application(db, app_id, current_user.organization_id)
    reports = (
        await db.execute(
            select(ScreeningReport)
            .where(ScreeningReport.application_id == app_id)
            .order_by(ScreeningReport.created_at.desc())
        )
    ).scalars().all()
    return reports


@router.post("/applications/{app_id}/convert", response_model=ApplicationResponse)
async def convert_application(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    application = await _get_application(db, app_id, current_user.organization_id)
    try:
        await svc.convert_to_resident(db, current_user.organization_id, application)
    except FunnelError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await db.commit()
    await db.refresh(application)
    return application


# ─── Lease e-signing (staff) ──────────────────────────────────────────────────

async def _load_signature_request(
    db: AsyncSession, request_id: uuid.UUID, org_id
) -> LeaseSignatureRequest:
    req = (
        await db.execute(
            select(LeaseSignatureRequest)
            .where(
                LeaseSignatureRequest.id == request_id,
                LeaseSignatureRequest.organization_id == org_id,
            )
            .options(selectinload(LeaseSignatureRequest.parties))
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lease signature request not found.")
    return req


@router.post("/lease-signatures", response_model=LeaseSignatureResponse, status_code=status.HTTP_201_CREATED)
async def create_lease_signature(
    payload: LeaseSignatureCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    for party in payload.parties:
        if party.role not in LEASE_PARTY_ROLES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid party role '{party.role}'.",
            )
    try:
        req = await svc.create_lease_signature_request(
            db,
            current_user.organization_id,
            title=payload.title,
            body=payload.body,
            parties=[
                {
                    "signer_name": p.signer_name,
                    "signer_email": str(p.signer_email),
                    "role": p.role,
                    "sign_order": p.sign_order if p.sign_order is not None else idx,
                }
                for idx, p in enumerate(payload.parties)
            ],
            resident_lease_id=payload.resident_lease_id,
            created_by_id=current_user.id,
            expires_at=payload.expires_at,
        )
    except FunnelError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await db.commit()
    req = await _load_signature_request(db, req.id, current_user.organization_id)
    return req


@router.post(
    "/lease-signatures/from-template",
    response_model=LeaseSignatureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lease_signature_from_template(
    payload: LeaseSignatureFromTemplate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    """Render a lease template for a resident lease and open a signing envelope."""
    org_id = current_user.organization_id
    for party in payload.parties or []:
        if party.role not in LEASE_PARTY_ROLES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid party role '{party.role}'.",
            )

    lease = (
        await db.execute(
            select(ResidentLease)
            .where(
                ResidentLease.id == payload.resident_lease_id,
                ResidentLease.organization_id == org_id,
                ResidentLease.is_deleted.is_(False),
            )
            .options(
                selectinload(ResidentLease.unit),
                selectinload(ResidentLease.occupants).selectinload(
                    ResidentLeaseOccupant.resident
                ),
            )
        )
    ).scalar_one_or_none()
    if lease is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resident lease not found")

    template = (
        await db.execute(
            select(LeaseTemplate).where(
                LeaseTemplate.id == payload.template_id,
                LeaseTemplate.organization_id == org_id,
                LeaseTemplate.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lease template not found")

    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()

    explicit_parties = None
    if payload.parties is not None:
        explicit_parties = [
            {
                "signer_name": p.signer_name,
                "signer_email": str(p.signer_email),
                "role": p.role,
                "sign_order": p.sign_order if p.sign_order is not None else idx,
            }
            for idx, p in enumerate(payload.parties)
        ]

    try:
        req = await svc.create_lease_signature_from_template(
            db,
            org_id,
            lease=lease,
            template=template,
            organization_name=org.name if org is not None else None,
            parties=explicit_parties,
            title=payload.title,
            created_by_id=current_user.id,
            expires_at=payload.expires_at,
        )
    except FunnelError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await db.commit()
    req = await _load_signature_request(db, req.id, org_id)
    return req


@router.get("/lease-signatures", response_model=list[LeaseSignatureResponse])
async def list_lease_signatures(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    resident_lease_id: uuid.UUID | None = Query(None),
):
    stmt = (
        select(LeaseSignatureRequest)
        .where(LeaseSignatureRequest.organization_id == current_user.organization_id)
        .options(selectinload(LeaseSignatureRequest.parties))
    )
    if resident_lease_id is not None:
        stmt = stmt.where(LeaseSignatureRequest.resident_lease_id == resident_lease_id)
    reqs = (
        await db.execute(stmt.order_by(LeaseSignatureRequest.created_at.desc()))
    ).scalars().unique().all()
    return reqs


@router.get("/lease-signatures/{request_id}", response_model=LeaseSignatureResponse)
async def get_lease_signature(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_signature_request(db, request_id, current_user.organization_id)


@router.post("/lease-signatures/{request_id}/void", response_model=LeaseSignatureResponse)
async def void_lease_signature(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(Editor),
):
    req = await _load_signature_request(db, request_id, current_user.organization_id)
    if req.status == "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "A completed lease cannot be voided.")
    req.status = "voided"
    await db.commit()
    req = await _load_signature_request(db, request_id, current_user.organization_id)
    return req


@router.get("/lease-signatures/{request_id}/pdf")
async def download_signed_lease(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = await _load_signature_request(db, request_id, current_user.organization_id)
    if req.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "The lease is not fully signed yet.")
    last = max(
        (p for p in req.parties if p.signed_at is not None),
        key=lambda p: p.signed_at,
        default=None,
    )
    pdf = waiver_service.generate_signed_pdf(
        title=req.title,
        body=req.rendered_body,
        document_hash=req.document_hash,
        signer_name=", ".join(p.signer_name for p in req.parties),
        signer_email=last.signer_email if last else None,
        signature_type=last.signature_type if last else "typed",
        signature_data=last.signature_data if last else "",
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        signed_at=req.completed_at,
        ip_address=last.ip_address if last else None,
        user_agent=last.user_agent if last else None,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="lease-{req.id}.pdf"'},
    )


# ─── Public: application submission ───────────────────────────────────────────

@public_router.post("/applications/public", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def submit_application(
    payload: ApplicationSubmit,
    db: AsyncSession = Depends(get_db),
):
    org = (
        await db.execute(
            select(Organization.id).where(Organization.id == payload.organization_id)
        )
    ).first()
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if payload.unit_id is not None:
        unit = (
            await db.execute(
                select(RentalUnit.id).where(
                    RentalUnit.id == payload.unit_id,
                    RentalUnit.organization_id == payload.organization_id,
                )
            )
        ).first()
        if unit is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rental unit not found.")
    application = RentalApplication(
        organization_id=payload.organization_id,
        unit_id=payload.unit_id,
        applicant_first_name=payload.applicant_first_name,
        applicant_last_name=payload.applicant_last_name,
        applicant_email=str(payload.applicant_email),
        applicant_phone=payload.applicant_phone,
        desired_move_in=payload.desired_move_in,
        monthly_income=payload.monthly_income,
        application_data=payload.application_data,
        status="submitted",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


# ─── Public: lease signing ────────────────────────────────────────────────────

async def _load_public(db: AsyncSession, token: str):
    loaded = await svc.load_request_by_token(db, token)
    if loaded is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signing link not found.")
    return loaded


@public_router.get("/lease-sign/{token}", response_model=PublicLeaseView)
async def public_view_lease(token: str, db: AsyncSession = Depends(get_db)):
    req, party = await _load_public(db, token)
    expired = svc.is_expired(req)
    if expired and req.status not in ("completed", "declined", "voided"):
        req.status = "expired"
        await db.commit()
    if party.status == "pending" and not expired and req.status in ("sent", "partially_signed"):
        party.status = "viewed"
        party.viewed_at = datetime.now().astimezone()
        await db.commit()
    return PublicLeaseView(
        title=req.title,
        body=req.rendered_body,
        request_status=req.status,
        party_status=party.status,
        signer_name=party.signer_name,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        expired=expired,
    )


@public_router.post("/lease-sign/{token}", response_model=PublicLeaseView)
async def public_sign_lease(
    token: str,
    payload: SignSubmission,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_agent: str | None = Header(None, alias="User-Agent"),
):
    req, party = await _load_public(db, token)
    if payload.signature_type not in LEASE_SIGNATURE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature type.")
    try:
        await svc.sign_party(
            db, req, party,
            signature_type=payload.signature_type,
            signature_data=payload.signature_data,
            consent_agreed=payload.consent_agreed,
            ip_address=request.client.host if request.client else None,
            user_agent=(user_agent or "")[:500] or None,
        )
    except FunnelError as e:
        await db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await db.commit()
    return PublicLeaseView(
        title=req.title,
        body=req.rendered_body,
        request_status=req.status,
        party_status=party.status,
        signer_name=party.signer_name,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        expired=False,
    )


@public_router.post("/lease-sign/{token}/decline", response_model=PublicLeaseView)
async def public_decline_lease(token: str, db: AsyncSession = Depends(get_db)):
    req, party = await _load_public(db, token)
    try:
        await svc.decline_party(db, req, party)
    except FunnelError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await db.commit()
    return PublicLeaseView(
        title=req.title,
        body=req.rendered_body,
        request_status=req.status,
        party_status=party.status,
        signer_name=party.signer_name,
        consent_text=waiver_service.ESIGN_CONSENT_TEXT,
        expired=False,
    )

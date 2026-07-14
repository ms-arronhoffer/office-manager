"""Vendor portal — token-gated endpoints for external vendor access."""
import secrets
import uuid
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, status, Header, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.attachment import Attachment
from app.models.entity_contact import EntityContact
from app.models.insurance_certificate import (
    CERT_TYPES,
    InsuranceCertificate,
    certificate_status,
)
from app.models.user import User
from app.models.vendor import Vendor
from app.models.maintenance_ticket import MaintenanceTicket
from app.schemas.attachment import AttachmentResponse
from app.schemas.entity_contact import (
    EntityContactCreate,
    EntityContactResponse,
    EntityContactUpdate,
)
from app.services.webhook_service import dispatch_webhook
from app.utils import file_storage

router = APIRouter()

_TOKEN_TTL_DAYS = 30
_VENDOR_ENTITY_TYPE = "vendor"


# ── Pydantic Schemas ────────────────────────────────────────────────────────

class PortalTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    portal_url: str


class VendorProfileResponse(BaseModel):
    id: uuid.UUID
    company_name: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    services: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class VendorProfileUpdate(BaseModel):
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None


class PortalTicketOffice(BaseModel):
    id: uuid.UUID
    location_name: Optional[str] = None

    class Config:
        from_attributes = True


class PortalTicketResponse(BaseModel):
    id: uuid.UUID
    subject: str
    priority: str
    status: str
    description: str
    location_hours: Optional[str] = None
    technician_name: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    vendor_completion_notes: Optional[str] = None
    vendor_completed_at: Optional[datetime] = None
    created_at: datetime
    office: Optional[PortalTicketOffice] = None

    class Config:
        from_attributes = True


class CompleteTicketRequest(BaseModel):
    notes: str


class PortalTicketUpdate(BaseModel):
    """Fields a vendor is allowed to update on an assigned ticket."""
    description: Optional[str] = None
    location_hours: Optional[str] = None
    technician_name: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    vendor_completion_notes: Optional[str] = None


class PortalCertResponse(BaseModel):
    """Read-only view of a vendor's certificate of insurance."""
    id: uuid.UUID
    certificate_type: str
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    limits: Optional[str] = None
    certificate_holder: Optional[str] = None
    notes: Optional[str] = None
    is_verified: bool
    status: str = ""  # computed
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _cert_to_portal_response(cert: InsuranceCertificate) -> PortalCertResponse:
    data = PortalCertResponse.model_validate(cert)
    data.status = certificate_status(cert.expiration_date)
    return data


# ── Auth dependency ─────────────────────────────────────────────────────────

async def get_portal_vendor(
    x_vendor_token: str = Header(None, alias="X-Vendor-Token"),
    db: AsyncSession = Depends(get_db),
) -> Vendor:
    if not x_vendor_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Vendor portal token required")
    result = await db.execute(
        select(Vendor).where(
            Vendor.portal_token == x_vendor_token,
            Vendor.deleted_at == None,  # noqa: E711
        )
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vendor token")
    if vendor.portal_token_expires_at and vendor.portal_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Vendor token expired")
    return vendor


# ── Internal: generate/refresh portal token (requires JWT admin/editor auth) ─

@router.post("/vendors/{vendor_id}/portal-token", response_model=PortalTokenResponse)
async def generate_portal_token(
    vendor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or refresh) a portal access token for a vendor. Admin/editor only."""
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    result = await db.execute(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.organization_id == current_user.organization_id,
            Vendor.deleted_at == None,  # noqa: E711
        )
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")

    token = secrets.token_hex(32)  # 64-char hex string
    expires_at = datetime.now(timezone.utc) + timedelta(days=_TOKEN_TTL_DAYS)

    vendor.portal_token = token
    vendor.portal_token_expires_at = expires_at
    await db.commit()

    return PortalTokenResponse(
        token=token,
        expires_at=expires_at,
        portal_url=f"/vendor-portal?token={token}",
    )


# ── Internal: assign vendor to ticket ──────────────────────────────────────

class AssignVendorRequest(BaseModel):
    vendor_id: Optional[uuid.UUID] = None


@router.patch("/maintenance-tickets/{ticket_id}/vendor", response_model=dict)
async def assign_vendor_to_ticket(
    ticket_id: uuid.UUID,
    payload: AssignVendorRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign or unassign a vendor to a maintenance ticket."""
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    result = await db.execute(
        select(MaintenanceTicket).where(
            MaintenanceTicket.id == ticket_id,
            MaintenanceTicket.organization_id == current_user.organization_id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    if payload.vendor_id is not None:
        # Verify vendor belongs to same org
        vendor_result = await db.execute(
            select(Vendor).where(
                Vendor.id == payload.vendor_id,
                Vendor.organization_id == current_user.organization_id,
                Vendor.deleted_at == None,  # noqa: E711
            )
        )
        if not vendor_result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")

    ticket.vendor_id = payload.vendor_id
    await db.commit()
    return {"ok": True}


# ── Portal: profile ─────────────────────────────────────────────────────────

@router.get("/vendor-portal/me", response_model=VendorProfileResponse)
async def portal_get_profile(vendor: Vendor = Depends(get_portal_vendor)):
    return vendor


@router.patch("/vendor-portal/me", response_model=VendorProfileResponse)
async def portal_update_profile(
    payload: VendorProfileUpdate,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(vendor, field, value)
    await db.commit()
    await db.refresh(vendor)
    return vendor


# ── Portal: tickets ─────────────────────────────────────────────────────────

@router.get("/vendor-portal/tickets", response_model=list[PortalTicketResponse])
async def portal_list_tickets(
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MaintenanceTicket)
        .options(selectinload(MaintenanceTicket.office))
        .where(
            MaintenanceTicket.vendor_id == vendor.id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
        .order_by(MaintenanceTicket.created_at.desc())
    )
    return result.scalars().all()


@router.get("/vendor-portal/tickets/{ticket_id}", response_model=PortalTicketResponse)
async def portal_get_ticket(
    ticket_id: uuid.UUID,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MaintenanceTicket)
        .options(selectinload(MaintenanceTicket.office))
        .where(
            MaintenanceTicket.id == ticket_id,
            MaintenanceTicket.vendor_id == vendor.id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


@router.patch("/vendor-portal/tickets/{ticket_id}", response_model=PortalTicketResponse)
async def portal_update_ticket(
    ticket_id: uuid.UUID,
    payload: PortalTicketUpdate,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """Allow the assigned vendor to update editable details on their ticket."""
    result = await db.execute(
        select(MaintenanceTicket)
        .options(selectinload(MaintenanceTicket.office))
        .where(
            MaintenanceTicket.id == ticket_id,
            MaintenanceTicket.vendor_id == vendor.id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)

    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.post("/vendor-portal/tickets/{ticket_id}/complete", response_model=PortalTicketResponse)
async def portal_complete_ticket(
    ticket_id: uuid.UUID,
    payload: CompleteTicketRequest,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """Mark a ticket as vendor-complete. Sets completion notes and timestamp; status moves to 'pending_review'."""
    result = await db.execute(
        select(MaintenanceTicket)
        .options(selectinload(MaintenanceTicket.office))
        .where(
            MaintenanceTicket.id == ticket_id,
            MaintenanceTicket.vendor_id == vendor.id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.vendor_completed_at:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ticket already marked complete")

    old_status = ticket.status
    ticket.vendor_completion_notes = payload.notes
    ticket.vendor_completed_at = datetime.now(timezone.utc)
    ticket.status = "pending_review"

    await db.commit()
    await db.refresh(ticket)

    # Fire webhook best-effort
    try:
        await dispatch_webhook(
            db,
            org_id=ticket.organization_id,
            event_type="ticket.vendor_completed",
            payload={
                "id": str(ticket.id),
                "subject": ticket.subject,
                "vendor_id": str(vendor.id),
                "vendor_name": vendor.company_name,
                "old_status": old_status,
                "new_status": ticket.status,
            },
        )
    except Exception:
        pass

    return ticket


# ── Portal: invoice upload ───────────────────────────────────────────────────

_ALLOWED_INVOICE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx"}


@router.post(
    "/vendor-portal/tickets/{ticket_id}/invoice",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def portal_upload_invoice(
    ticket_id: uuid.UUID,
    file: UploadFile = File(...),
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """Upload an invoice or completion document for an assigned ticket."""
    result = await db.execute(
        select(MaintenanceTicket).where(
            MaintenanceTicket.id == ticket_id,
            MaintenanceTicket.vendor_id == vendor.id,
            MaintenanceTicket.deleted_at == None,  # noqa: E711
        )
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_INVOICE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not allowed for invoices.",
        )

    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB} MB.",
        )

    stored_name = f"{uuid.uuid4()}{ext}"
    file_storage.save_file("maintenance_ticket", stored_name, content)

    attachment = Attachment(
        organization_id=ticket.organization_id,
        entity_type="maintenance_ticket",
        entity_id=ticket_id,
        original_filename=Path(file.filename).name,
        stored_filename=stored_name,
        content_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        uploaded_by=vendor.company_name,
        description="invoice",
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return AttachmentResponse.model_validate(attachment, from_attributes=True)


# ── Portal: insurance certificates (COIs) ───────────────────────────────────

_ALLOWED_COI_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}


@router.get("/vendor-portal/insurance", response_model=list[PortalCertResponse])
async def portal_list_insurance(
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """List the vendor's certificates of insurance with expiration status."""
    result = await db.execute(
        select(InsuranceCertificate)
        .where(
            InsuranceCertificate.vendor_id == vendor.id,
            InsuranceCertificate.organization_id == vendor.organization_id,
        )
        .order_by(InsuranceCertificate.expiration_date.asc().nulls_last())
    )
    return [_cert_to_portal_response(c) for c in result.scalars().all()]


@router.post(
    "/vendor-portal/insurance/reupload",
    response_model=PortalCertResponse,
    status_code=status.HTTP_201_CREATED,
)
async def portal_reupload_insurance(
    file: UploadFile = File(...),
    cert_id: Optional[uuid.UUID] = Form(None),
    certificate_type: str = Form("general_liability"),
    insurer: Optional[str] = Form(None),
    policy_number: Optional[str] = Form(None),
    effective_date: Optional[str] = Form(None),
    expiration_date: Optional[str] = Form(None),
    limits: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """Submit a renewed certificate of insurance.

    Creates a new ``InsuranceCertificate`` (or updates ``cert_id`` when it
    belongs to this vendor), stores the uploaded file as an attachment, and marks
    the certificate ``is_verified=False`` so an admin reviews it.
    """
    if certificate_type not in CERT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid certificate_type. Must be one of: {list(CERT_TYPES)}",
        )

    def _parse_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid date '{value}'. Use YYYY-MM-DD.",
            )

    eff = _parse_date(effective_date)
    exp = _parse_date(expiration_date)

    # Validate the uploaded file up front.
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_COI_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not allowed for certificates.",
        )
    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB} MB.",
        )

    if cert_id is not None:
        result = await db.execute(
            select(InsuranceCertificate).where(
                InsuranceCertificate.id == cert_id,
                InsuranceCertificate.vendor_id == vendor.id,
                InsuranceCertificate.organization_id == vendor.organization_id,
            )
        )
        cert = result.scalar_one_or_none()
        if not cert:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
        cert.certificate_type = certificate_type
        if insurer is not None:
            cert.insurer = insurer
        if policy_number is not None:
            cert.policy_number = policy_number
        if eff is not None:
            cert.effective_date = eff
        if exp is not None:
            cert.expiration_date = exp
        if limits is not None:
            cert.limits = limits
        if notes is not None:
            cert.notes = notes
    else:
        cert = InsuranceCertificate(
            organization_id=vendor.organization_id,
            vendor_id=vendor.id,
            certificate_type=certificate_type,
            insurer=insurer,
            policy_number=policy_number,
            effective_date=eff,
            expiration_date=exp,
            limits=limits,
            notes=notes,
        )
        db.add(cert)

    # Re-uploaded certificates always require admin re-verification.
    cert.is_verified = False
    cert.verified_at = None

    await db.flush()  # ensure cert.id is available for the attachment

    stored_name = f"{uuid.uuid4()}{ext}"
    file_storage.save_file("insurance_certificate", stored_name, content)

    attachment = Attachment(
        organization_id=vendor.organization_id,
        entity_type="insurance_certificate",
        entity_id=cert.id,
        original_filename=Path(file.filename).name,
        stored_filename=stored_name,
        content_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        uploaded_by=vendor.company_name,
        description="coi",
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(cert)
    return _cert_to_portal_response(cert)


# ── Portal: additional contacts (editable) ──────────────────────────────────

@router.get("/vendor-portal/contacts", response_model=list[EntityContactResponse])
async def portal_list_contacts(
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """List the vendor's additional contacts."""
    result = await db.execute(
        select(EntityContact)
        .where(
            EntityContact.entity_type == _VENDOR_ENTITY_TYPE,
            EntityContact.entity_id == vendor.id,
            EntityContact.organization_id == vendor.organization_id,
        )
        .order_by(EntityContact.is_primary.desc(), EntityContact.contact_name)
    )
    return [EntityContactResponse.model_validate(c, from_attributes=True) for c in result.scalars().all()]


@router.post(
    "/vendor-portal/contacts",
    response_model=EntityContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def portal_create_contact(
    payload: EntityContactCreate,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    """Create an additional contact for the authenticated vendor."""
    data = payload.model_dump()
    # Force entity scoping from the authenticated vendor; never trust the body.
    data["entity_type"] = _VENDOR_ENTITY_TYPE
    data["entity_id"] = vendor.id
    contact = EntityContact(**data, organization_id=vendor.organization_id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return EntityContactResponse.model_validate(contact, from_attributes=True)


async def _load_vendor_contact(
    db: AsyncSession, contact_id: uuid.UUID, vendor: Vendor
) -> EntityContact:
    result = await db.execute(
        select(EntityContact).where(
            EntityContact.id == contact_id,
            EntityContact.entity_type == _VENDOR_ENTITY_TYPE,
            EntityContact.entity_id == vendor.id,
            EntityContact.organization_id == vendor.organization_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.put("/vendor-portal/contacts/{contact_id}", response_model=EntityContactResponse)
async def portal_update_contact(
    contact_id: uuid.UUID,
    payload: EntityContactUpdate,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    contact = await _load_vendor_contact(db, contact_id, vendor)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    await db.commit()
    await db.refresh(contact)
    return EntityContactResponse.model_validate(contact, from_attributes=True)


@router.delete("/vendor-portal/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def portal_delete_contact(
    contact_id: uuid.UUID,
    vendor: Vendor = Depends(get_portal_vendor),
    db: AsyncSession = Depends(get_db),
):
    contact = await _load_vendor_contact(db, contact_id, vendor)
    await db.delete(contact)
    await db.commit()

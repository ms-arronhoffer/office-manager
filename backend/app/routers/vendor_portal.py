"""Vendor portal — token-gated endpoints for external vendor access."""
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, status, Header, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.attachment import Attachment
from app.models.user import User
from app.models.vendor import Vendor
from app.models.maintenance_ticket import MaintenanceTicket
from app.schemas.attachment import AttachmentResponse
from app.services.webhook_service import dispatch_webhook

router = APIRouter()

_TOKEN_TTL_DAYS = 30


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
    vendor_completion_notes: Optional[str] = None
    vendor_completed_at: Optional[datetime] = None
    created_at: datetime
    office: Optional[PortalTicketOffice] = None

    class Config:
        from_attributes = True


class CompleteTicketRequest(BaseModel):
    notes: str


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

    upload_dir = Path(settings.UPLOAD_DIR) / "maintenance_ticket"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{ext}"
    (upload_dir / stored_name).write_bytes(content)

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

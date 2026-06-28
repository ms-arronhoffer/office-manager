"""Insurance certificates CRUD and compliance reporting."""
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.insurance_certificate import InsuranceCertificate, certificate_status
from app.models.vendor import Vendor
from app.models.landlord import Landlord

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class CertCreate(BaseModel):
    vendor_id: Optional[uuid.UUID] = None
    landlord_id: Optional[uuid.UUID] = None
    certificate_type: str
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    limits: Optional[str] = None
    certificate_holder: Optional[str] = None
    notes: Optional[str] = None


class CertUpdate(BaseModel):
    certificate_type: Optional[str] = None
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    limits: Optional[str] = None
    certificate_holder: Optional[str] = None
    notes: Optional[str] = None
    is_verified: Optional[bool] = None


class CertVendorSummary(BaseModel):
    id: str
    company_name: str

    class Config:
        from_attributes = True


class CertLandlordSummary(BaseModel):
    id: str
    company_name: str

    class Config:
        from_attributes = True


class CertResponse(BaseModel):
    id: uuid.UUID
    organization_id: Optional[uuid.UUID] = None
    vendor_id: Optional[uuid.UUID] = None
    landlord_id: Optional[uuid.UUID] = None
    certificate_type: str
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    limits: Optional[str] = None
    certificate_holder: Optional[str] = None
    notes: Optional[str] = None
    is_verified: bool
    verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    vendor: Optional[CertVendorSummary] = None
    landlord: Optional[CertLandlordSummary] = None
    status: str = ""  # computed

    class Config:
        from_attributes = True


def _compute_status(cert: InsuranceCertificate) -> str:
    return certificate_status(cert.expiration_date)


def _to_response(cert: InsuranceCertificate) -> CertResponse:
    data = CertResponse.model_validate(cert)
    data.status = _compute_status(cert)
    return data


# ── Compliance summary ────────────────────────────────────────────────────────

class ComplianceSummary(BaseModel):
    total: int
    active: int
    expiring_soon: int
    expired: int
    unknown: int


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CertResponse])
async def list_certs(
    vendor_id: Optional[uuid.UUID] = Query(None),
    landlord_id: Optional[uuid.UUID] = Query(None),
    expired_only: bool = Query(False),
    expiring_within_days: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(InsuranceCertificate)
        .options(
            selectinload(InsuranceCertificate.vendor),
            selectinload(InsuranceCertificate.landlord),
        )
        .where(InsuranceCertificate.organization_id == current_user.organization_id)
    )
    if vendor_id:
        q = q.where(InsuranceCertificate.vendor_id == vendor_id)
    if landlord_id:
        q = q.where(InsuranceCertificate.landlord_id == landlord_id)
    if expired_only:
        q = q.where(InsuranceCertificate.expiration_date < date.today())
    if expiring_within_days is not None:
        from datetime import timedelta
        cutoff = date.today() + timedelta(days=expiring_within_days)
        q = q.where(
            InsuranceCertificate.expiration_date >= date.today(),
            InsuranceCertificate.expiration_date <= cutoff,
        )
    q = q.order_by(InsuranceCertificate.expiration_date.asc().nulls_last())
    result = await db.execute(q)
    return [_to_response(c) for c in result.scalars().all()]


@router.get("/compliance", response_model=ComplianceSummary)
async def compliance_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(InsuranceCertificate).where(
            InsuranceCertificate.organization_id == current_user.organization_id
        )
    )
    certs = result.scalars().all()
    statuses = [_compute_status(c) for c in certs]
    return ComplianceSummary(
        total=len(certs),
        active=statuses.count("active"),
        expiring_soon=statuses.count("expiring_soon"),
        expired=statuses.count("expired"),
        unknown=statuses.count("unknown"),
    )


@router.get("/{cert_id}", response_model=CertResponse)
async def get_cert(
    cert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(InsuranceCertificate)
        .options(
            selectinload(InsuranceCertificate.vendor),
            selectinload(InsuranceCertificate.landlord),
        )
        .where(
            InsuranceCertificate.id == cert_id,
            InsuranceCertificate.organization_id == current_user.organization_id,
        )
    )
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
    return _to_response(cert)


@router.post("", response_model=CertResponse, status_code=status.HTTP_201_CREATED)
async def create_cert(
    payload: CertCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if not payload.vendor_id and not payload.landlord_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="vendor_id or landlord_id required")

    cert = InsuranceCertificate(
        organization_id=current_user.organization_id,
        **payload.model_dump(),
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    # Reload relationships
    result = await db.execute(
        select(InsuranceCertificate)
        .options(
            selectinload(InsuranceCertificate.vendor),
            selectinload(InsuranceCertificate.landlord),
        )
        .where(InsuranceCertificate.id == cert.id)
    )
    return _to_response(result.scalar_one())


@router.patch("/{cert_id}", response_model=CertResponse)
async def update_cert(
    cert_id: uuid.UUID,
    payload: CertUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    result = await db.execute(
        select(InsuranceCertificate)
        .options(
            selectinload(InsuranceCertificate.vendor),
            selectinload(InsuranceCertificate.landlord),
        )
        .where(
            InsuranceCertificate.id == cert_id,
            InsuranceCertificate.organization_id == current_user.organization_id,
        )
    )
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(cert, field, value)

    if payload.is_verified is True and not cert.verified_at:
        cert.verified_at = datetime.now(timezone.utc)
    elif payload.is_verified is False:
        cert.verified_at = None

    await db.commit()
    await db.refresh(cert)
    result = await db.execute(
        select(InsuranceCertificate)
        .options(
            selectinload(InsuranceCertificate.vendor),
            selectinload(InsuranceCertificate.landlord),
        )
        .where(InsuranceCertificate.id == cert.id)
    )
    return _to_response(result.scalar_one())


@router.delete("/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cert(
    cert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    result = await db.execute(
        select(InsuranceCertificate).where(
            InsuranceCertificate.id == cert_id,
            InsuranceCertificate.organization_id == current_user.organization_id,
        )
    )
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
    await db.delete(cert)
    await db.commit()

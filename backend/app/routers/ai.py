"""AI-assist API (Google Gemini).

Mounted at ``/api/v1/ai`` behind ``enforce_org_access``. Endpoints return
*suggestions* for human review; nothing is auto-committed.

Gating:

* ``POST /ai/leases/parse`` — **basic lease detail ingestion**, available on all
  tiers (not gated by ``ai_assist``).
* ``POST /ai/leases/{lease_id}/abstract/suggest`` — Pro+ (``ai_assist``).
* ``POST /ai/reports/summary`` — Pro+ (``ai_assist``).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_feature
from app.config import settings
from app.database import get_db
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.user import User
from app.services import ai_service
from app.services.lease_abstract_catalog import CLAUSE_CATEGORIES

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class AIStatusResponse(BaseModel):
    configured: bool
    model: str


class LeaseParseResponse(BaseModel):
    suggested: dict
    model: str


class AbstractSuggestResponse(BaseModel):
    suggested: dict
    model: str


class SummaryRequest(BaseModel):
    period: str = "weekly"  # 'weekly' | 'monthly'


class SummaryResponse(BaseModel):
    period: str
    period_label: str
    narrative: str
    data: dict
    model: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _allowed_extensions() -> set[str]:
    return {ext.strip().lower() for ext in settings.ALLOWED_EXTENSIONS.split(",")}


async def _read_document(file: UploadFile) -> tuple[bytes, str]:
    """Validate and read an uploaded document, returning (bytes, mime_type)."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in _allowed_extensions():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not allowed. Allowed: {settings.ALLOWED_EXTENSIONS}",
        )
    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB} MB.",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    mime_type = file.content_type or _MIME_BY_EXT.get(ext, "application/octet-stream")
    return content, mime_type


_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _ai_error_response(exc: ai_service.AIError) -> HTTPException:
    if isinstance(exc, ai_service.AIUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=AIStatusResponse)
async def ai_status(current_user: User = Depends(get_current_user)):
    """Report whether AI assist is configured (for the UI to show/hide actions)."""
    return AIStatusResponse(configured=ai_service.is_configured(), model=settings.GEMINI_MODEL)


# ── Basic lease ingestion (all tiers) ─────────────────────────────────────────

@router.post("/leases/parse", response_model=LeaseParseResponse)
async def parse_lease(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Extract suggested lease fields from an uploaded document.

    Basic lease-detail ingestion is available on every plan, so this endpoint is
    intentionally **not** gated behind ``ai_assist``.
    """
    content, mime_type = await _read_document(file)
    try:
        suggested = await ai_service.parse_lease_document(content, mime_type)
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    return LeaseParseResponse(suggested=suggested, model=settings.GEMINI_MODEL)


# ── Lease abstract suggestions (Pro+) ─────────────────────────────────────────

@router.post(
    "/leases/{lease_id}/abstract/suggest",
    response_model=AbstractSuggestResponse,
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def suggest_abstract(
    lease_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Propose lease-abstract clause content for each catalog category."""
    result = await db.execute(
        select(Lease).where(
            Lease.id == lease_id,
            Lease.is_deleted.is_(False),
            Lease.organization_id == current_user.organization_id,
        )
    )
    lease = result.scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    content, mime_type = await _read_document(file)
    categories = [{"key": c["key"], "name": c["name"]} for c in CLAUSE_CATEGORIES]
    try:
        suggested = await ai_service.suggest_abstract_clauses(content, mime_type, categories)
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    return AbstractSuggestResponse(suggested=suggested, model=settings.GEMINI_MODEL)


# ── Narrative summary report (Pro+) ───────────────────────────────────────────

async def _aggregate_summary(db: AsyncSession, org_id, horizon_days: int) -> dict:
    """Aggregate the org's upcoming notices/expirations and maintenance load."""
    today = date.today()
    horizon = today + timedelta(days=horizon_days)
    overdue_cutoff = datetime.now() - timedelta(days=7)

    open_tickets = (
        await db.execute(
            select(func.count(MaintenanceTicket.id)).where(
                MaintenanceTicket.organization_id == org_id,
                MaintenanceTicket.status.in_(["open", "in_progress"]),
                MaintenanceTicket.is_deleted.is_(False),
            )
        )
    ).scalar_one()

    overdue = (
        await db.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.organization_id == org_id,
                MaintenanceTicket.status.in_(["open", "in_progress"]),
                MaintenanceTicket.created_at < overdue_cutoff,
                MaintenanceTicket.is_deleted.is_(False),
            )
            .order_by(MaintenanceTicket.created_at.asc())
            .limit(15)
        )
    ).scalars().all()

    expiring = (
        await db.execute(
            select(Lease)
            .where(
                Lease.organization_id == org_id,
                Lease.lease_expiration.is_not(None),
                Lease.lease_expiration <= horizon,
                Lease.lease_expiration >= today,
                Lease.is_deleted.is_(False),
            )
            .order_by(Lease.lease_expiration.asc())
            .limit(25)
        )
    ).scalars().all()

    upcoming_notices = (
        await db.execute(
            select(Lease)
            .where(
                Lease.organization_id == org_id,
                Lease.lease_notice_date.is_not(None),
                Lease.lease_notice_date <= horizon,
                Lease.lease_notice_date >= today,
                Lease.notice_given_date.is_(None),
                Lease.is_deleted.is_(False),
            )
            .order_by(Lease.lease_notice_date.asc())
            .limit(25)
        )
    ).scalars().all()

    return {
        "horizon_days": horizon_days,
        "open_tickets": int(open_tickets),
        "overdue_tickets": [
            {
                "subject": t.subject,
                "days_open": (datetime.now() - t.created_at).days if t.created_at else None,
            }
            for t in overdue
        ],
        "leases_expiring": [
            {
                "name": l.lease_name,
                "lessor": l.lessor_name,
                "expires": l.lease_expiration.isoformat() if l.lease_expiration else None,
            }
            for l in expiring
        ],
        "upcoming_notice_deadlines": [
            {
                "name": l.lease_name,
                "lessor": l.lessor_name,
                "notice_due": l.lease_notice_date.isoformat() if l.lease_notice_date else None,
                "notice_period": l.notice_period,
            }
            for l in upcoming_notices
        ],
    }


@router.post(
    "/reports/summary",
    response_model=SummaryResponse,
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def summary_report(
    payload: SummaryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a narrative weekly/monthly operations briefing."""
    period = payload.period if payload.period in ("weekly", "monthly") else "weekly"
    horizon_days = 30 if period == "weekly" else 90
    period_label = (
        f"Week of {date.today().strftime('%B %d, %Y')}"
        if period == "weekly"
        else date.today().strftime("%B %Y")
    )

    data = await _aggregate_summary(db, current_user.organization_id, horizon_days)
    try:
        narrative = await ai_service.generate_summary_narrative(period_label, data)
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    return SummaryResponse(
        period=period,
        period_label=period_label,
        narrative=narrative,
        data=data,
        model=settings.GEMINI_MODEL,
    )

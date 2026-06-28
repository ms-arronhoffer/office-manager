"""AI-assist API (Google Gemini).

Mounted at ``/api/v1/ai`` behind ``enforce_org_access``. Endpoints return
*suggestions* for human review; nothing is auto-committed.

Gating:

* ``POST /ai/leases/parse`` — **basic lease detail ingestion**, available on all
  tiers (not gated by ``ai_assist``).
* ``POST /ai/leases/{lease_id}/abstract/suggest`` — Pro+ (``ai_assist``).
* ``POST /ai/reports/summary`` — Pro+ (``ai_assist``).
* ``POST /ai/portfolio/ask`` — Pro+ (``ai_assist``); grounded portfolio Q&A (RAG).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_feature
from app.config import settings
from app.database import get_db
from app.models.hvac_contract import HvacContract
from app.models.insurance_certificate import InsuranceCertificate
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill
from app.services import (
    ai_service,
    ap_service,
    document_extraction,
    document_search_service,
    report_export,
)
from app.services.lease_abstract_catalog import CLAUSE_CATEGORIES

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class AIStatusResponse(BaseModel):
    configured: bool
    model: str


class LeaseParseResponse(BaseModel):
    suggested: dict
    model: str


class EntityMatch(BaseModel):
    entity_type: str  # 'vendor' | 'landlord' | 'lease'
    id: str
    name: str


class DocumentClassifyResponse(BaseModel):
    document_type: str
    confidence: str
    reasoning: str = ""
    fields: dict
    suggested_matches: list[EntityMatch] = Field(default_factory=list)
    model: str


class AbstractSuggestResponse(BaseModel):
    suggested: dict
    model: str


class TicketTriageRequest(BaseModel):
    subject: str = Field(min_length=1)
    description: str = ""


class TicketTriageResponse(BaseModel):
    suggested: dict
    model: str


class SummaryRequest(BaseModel):
    period: str = "weekly"  # 'weekly' | 'monthly'


class SummaryActionItem(BaseModel):
    title: str
    detail: str = ""
    priority: str = "medium"
    category: str = "other"


class SummaryResponse(BaseModel):
    period: str
    period_label: str
    narrative: str
    narrative_html: str
    recommended_actions: list[SummaryActionItem] = Field(default_factory=list)
    data: dict
    model: str


class SummaryExportRequest(BaseModel):
    narrative: str = Field(min_length=1)
    period_label: str = "Operations Briefing"
    format: str = "pdf"  # 'pdf' | 'docx'


class PortfolioAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=20)


class PortfolioCitation(BaseModel):
    index: int
    lease_id: str
    lease_name: str | None = None
    attachment_id: str | None = None
    source_filename: str
    chunk_index: int | None = None
    snippet: str
    score: float
    match_type: str


class PortfolioAskResponse(BaseModel):
    question: str
    answer: str
    answer_html: str
    citations: list[PortfolioCitation]
    grounded: bool
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
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Extensions whose bytes Gemini cannot read inline — we extract text first.
_TEXT_EXTRACT_EXTS = {".docx", ".doc", ".txt"}


def _maybe_extract_text(filename: str | None, content: bytes) -> str | None:
    """Extract plain text for formats Gemini cannot read inline.

    Word/text documents (``_TEXT_EXTRACT_EXTS``) must be converted to text
    before being sent to the model — passing their raw bytes inline yields an
    empty/garbage response. PDFs and images return ``None`` so the caller sends
    the bytes inline instead.
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in _TEXT_EXTRACT_EXTS:
        return None
    try:
        text_content = document_extraction.extract_text(content, filename or "")
    except (
        document_extraction.UnsupportedDocumentError,
        document_extraction.DocumentExtractionError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not text_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The document did not contain any readable text.",
        )
    return text_content


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
    text_content = _maybe_extract_text(file.filename, content)

    try:
        suggested = await ai_service.parse_lease_document(
            content, mime_type, text_content=text_content
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    return LeaseParseResponse(suggested=suggested, model=settings.GEMINI_MODEL)


# ── Inbound document classification & routing (Pro+) ──────────────────────────

def _norm_name(value: str | None) -> str:
    """Normalise an entity name for fuzzy matching (case/space-insensitive)."""
    return " ".join((value or "").lower().split())


def _name_matches(needle: str, candidate: str) -> bool:
    """Return whether two normalised names plausibly refer to the same entity."""
    if not needle or not candidate:
        return False
    return needle == candidate or needle in candidate or candidate in needle


async def _route_classification(
    db: AsyncSession, org_id, result: dict
) -> list[EntityMatch]:
    """Find existing org records that the classified document likely belongs to.

    Matching is intentionally conservative (exact or substring on normalised
    names) and returns *suggestions* only — nothing is auto-linked.
    """
    doc_type = result.get("document_type")
    fields = result.get("fields") or {}
    matches: list[EntityMatch] = []

    # Vendor invoices and COIs route to the vendor that issued/holds them.
    vendor_name = _norm_name(
        fields.get("vendor_name") or fields.get("insured_name")
    )
    if doc_type in ("vendor_invoice", "insurance_certificate") and vendor_name:
        rows = (
            await db.execute(
                select(Vendor.id, Vendor.company_name).where(
                    Vendor.organization_id == org_id,
                    Vendor.is_deleted.is_(False),
                )
            )
        ).all()
        for vid, name in rows:
            if _name_matches(vendor_name, _norm_name(name)):
                matches.append(
                    EntityMatch(entity_type="vendor", id=str(vid), name=name)
                )

    # COIs may instead (or also) cover a landlord; amendments/leases name a lessor.
    landlord_name = _norm_name(
        fields.get("insured_name") or fields.get("lessor_name")
    )
    if doc_type in (
        "insurance_certificate",
        "lease_amendment",
        "lease",
    ) and landlord_name:
        rows = (
            await db.execute(
                select(Landlord.id, Landlord.landlord_company).where(
                    Landlord.organization_id == org_id,
                    Landlord.is_deleted.is_(False),
                )
            )
        ).all()
        for lid, name in rows:
            if _name_matches(landlord_name, _norm_name(name)):
                matches.append(
                    EntityMatch(entity_type="landlord", id=str(lid), name=name)
                )

    # Amendments route to the existing lease they modify.
    if doc_type in ("lease_amendment", "lease"):
        lease_needle = _norm_name(fields.get("lease_name"))
        lessor_needle = _norm_name(fields.get("lessor_name"))
        if lease_needle or lessor_needle:
            rows = (
                await db.execute(
                    select(Lease.id, Lease.lease_name, Lease.lessor_name).where(
                        Lease.organization_id == org_id,
                        Lease.is_deleted.is_(False),
                    )
                )
            ).all()
            for lid, lease_name, lessor_name in rows:
                if (lease_needle and _name_matches(lease_needle, _norm_name(lease_name))) or (
                    lessor_needle and _name_matches(lessor_needle, _norm_name(lessor_name))
                ):
                    matches.append(
                        EntityMatch(entity_type="lease", id=str(lid), name=lease_name)
                    )

    return matches


@router.post(
    "/documents/classify",
    response_model=DocumentClassifyResponse,
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def classify_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Classify an inbound document and suggest the record/entity to route it to.

    Extends the lease-parse pattern to vendor invoices (AP), certificates of
    insurance (COIs), and lease amendments: the model determines the document
    type, extracts the type's fields for pre-fill, and the org's existing
    vendors/landlords/leases are searched for likely matches. Everything is
    returned for human review — nothing is auto-committed.
    """
    content, mime_type = await _read_document(file)
    text_content = _maybe_extract_text(file.filename, content)

    try:
        result = await ai_service.classify_document(
            content, mime_type, text_content=text_content
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)

    suggested_matches = await _route_classification(
        db, current_user.organization_id, result
    )
    return DocumentClassifyResponse(
        document_type=result["document_type"],
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        fields=result["fields"],
        suggested_matches=suggested_matches,
        model=settings.GEMINI_MODEL,
    )

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
    text_content = _maybe_extract_text(file.filename, content)
    categories = [
        {"key": c["key"], "name": c["name"], "fields": c["fields"]}
        for c in CLAUSE_CATEGORIES
    ]
    try:
        suggested = await ai_service.suggest_abstract_clauses(
            content, mime_type, categories, text_content=text_content
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    return AbstractSuggestResponse(suggested=suggested, model=settings.GEMINI_MODEL)


# ── Maintenance ticket triage (Pro+) ──────────────────────────────────────────

@router.post(
    "/tickets/triage",
    response_model=TicketTriageResponse,
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def triage_ticket(
    payload: TicketTriageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest a category, priority, vendor, and draft response for a ticket.

    The recommendation is grounded in the org's own categories and vendors and
    is returned for human review — nothing is auto-assigned.
    """
    org_id = current_user.organization_id

    cat_rows = (
        await db.execute(
            select(TicketCategory.id, TicketCategory.name)
            # Include org-specific categories as well as the global/default
            # categories (organization_id IS NULL) shared across all orgs.
            .where(
                or_(
                    TicketCategory.organization_id == org_id,
                    TicketCategory.organization_id.is_(None),
                )
            )
            .order_by(TicketCategory.name.asc())
        )
    ).all()
    categories = [{"id": str(cid), "name": name} for cid, name in cat_rows]

    vendor_rows = (
        await db.execute(
            select(Vendor.id, Vendor.company_name, Vendor.services, Vendor.is_preferred)
            .where(
                Vendor.organization_id == org_id,
                Vendor.is_deleted.is_(False),
            )
            .order_by(Vendor.company_name.asc())
        )
    ).all()
    vendors = [
        {
            "id": str(vid),
            "name": name,
            "services": services,
            "preferred": bool(preferred),
        }
        for vid, name, services, preferred in vendor_rows
    ]

    try:
        suggested = await ai_service.triage_ticket(
            payload.subject, payload.description, categories, vendors
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    return TicketTriageResponse(suggested=suggested, model=settings.GEMINI_MODEL)


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

    # Certificates of insurance (COIs) expiring within the horizon. Already-expired
    # certificates are surfaced too (a lapsed COI is a live risk), bounded to the
    # recent past so the briefing stays actionable.
    coi_floor = today - timedelta(days=horizon_days)
    expiring_cois = (
        await db.execute(
            select(InsuranceCertificate)
            .where(
                InsuranceCertificate.organization_id == org_id,
                InsuranceCertificate.expiration_date.is_not(None),
                InsuranceCertificate.expiration_date <= horizon,
                InsuranceCertificate.expiration_date >= coi_floor,
            )
            .options(
                selectinload(InsuranceCertificate.vendor),
                selectinload(InsuranceCertificate.landlord),
            )
            .order_by(InsuranceCertificate.expiration_date.asc())
            .limit(25)
        )
    ).scalars().all()

    # HVAC service / contract renewals coming due within the horizon.
    hvac_renewals = (
        await db.execute(
            select(HvacContract)
            .where(
                HvacContract.organization_id == org_id,
                HvacContract.next_service_date.is_not(None),
                HvacContract.next_service_date <= horizon,
                HvacContract.next_service_date >= today,
                HvacContract.is_deleted.is_(False),
            )
            .order_by(HvacContract.next_service_date.asc())
            .limit(25)
        )
    ).scalars().all()

    # Past-due accounts-payable: finalized vendor bills whose due date has passed
    # and still carry an outstanding balance (posted to the GL via the ``ap`` tag).
    overdue_bills = (
        await db.execute(
            select(VendorBill)
            .where(
                VendorBill.organization_id == org_id,
                VendorBill.status == "finalized",
                VendorBill.due_date.is_not(None),
                VendorBill.due_date < today,
            )
            .options(
                selectinload(VendorBill.lines),
                selectinload(VendorBill.payments),
                selectinload(VendorBill.vendor),
            )
            .order_by(VendorBill.due_date.asc())
            .limit(25)
        )
    ).scalars().all()
    past_due_payables = []
    for bill in overdue_bills:
        balance = ap_service.balance_due(bill)
        if balance <= 0:
            continue
        past_due_payables.append(
            {
                "vendor": bill.vendor.company_name if bill.vendor else None,
                "bill_number": bill.bill_number,
                "due_date": bill.due_date.isoformat() if bill.due_date else None,
                "days_overdue": (today - bill.due_date).days if bill.due_date else None,
                "balance_due": float(balance),
            }
        )

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
        "expiring_cois": [
            {
                "holder": c.vendor.company_name
                if c.vendor
                else (
                    (c.landlord.landlord_company or c.landlord.office_name)
                    if c.landlord
                    else None
                ),
                "certificate_type": c.certificate_type,
                "insurer": c.insurer,
                "expires": c.expiration_date.isoformat() if c.expiration_date else None,
                "expired": bool(c.expiration_date and c.expiration_date < today),
            }
            for c in expiring_cois
        ],
        "hvac_renewals": [
            {
                "office": h.office_name,
                "hvac_company": h.hvac_company,
                "frequency": h.frequency,
                "next_service": h.next_service_date.isoformat()
                if h.next_service_date
                else None,
            }
            for h in hvac_renewals
        ],
        "past_due_payables": past_due_payables,
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

    # Recommended actions are an additive, best-effort section: if that second
    # generation fails we still return the narrative rather than 500 the request.
    try:
        recommended_actions = await ai_service.generate_recommended_actions(
            period_label, data
        )
    except ai_service.AIError:
        recommended_actions = []

    return SummaryResponse(
        period=period,
        period_label=period_label,
        narrative=narrative,
        narrative_html=report_export.markdown_to_html(narrative),
        recommended_actions=[SummaryActionItem(**a) for a in recommended_actions],
        data=data,
        model=settings.GEMINI_MODEL,
    )


@router.post(
    "/reports/summary/export",
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def export_summary_report(
    payload: SummaryExportRequest,
    current_user: User = Depends(get_current_user),
):
    """Render a briefing's Markdown to a downloadable PDF or DOCX file."""
    fmt = payload.format.lower()
    if fmt not in report_export.EXPORT_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{payload.format}'. Use one of: "
            f"{', '.join(report_export.EXPORT_FORMATS)}.",
        )

    safe_label = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in payload.period_label
    ).strip("_") or "briefing"

    if fmt == "pdf":
        content = report_export.markdown_to_pdf(payload.narrative, title=payload.period_label)
        media_type = "application/pdf"
        filename = f"{safe_label}.pdf"
    else:
        content = report_export.markdown_to_docx(payload.narrative, title=payload.period_label)
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        filename = f"{safe_label}.docx"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Portfolio Q&A (RAG "Ask your portfolio") (Pro+) ───────────────────────────

@router.post(
    "/portfolio/ask",
    response_model=PortfolioAskResponse,
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def ask_portfolio(
    payload: PortfolioAskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Answer a natural-language question grounded in the org's lease documents.

    Reuses the existing semantic/keyword document retrieval to pull the most
    relevant lease document chunks, then adds a generation step that composes a
    grounded answer citing those passages. Citations map back to the lease
    document chunks the answer relied on. When no relevant documents are found
    the answer reports that plainly without calling the model.
    """
    matches = await document_search_service.search_documents(
        db,
        organization_id=current_user.organization_id,
        query=payload.question,
        limit=payload.limit,
    )

    citations = [
        PortfolioCitation(index=i, **match)
        for i, match in enumerate(matches, start=1)
    ]

    if not matches:
        answer = (
            "I couldn't find any indexed lease documents relevant to that "
            "question. Try rephrasing, or make sure the related lease documents "
            "have been uploaded and indexed."
        )
        return PortfolioAskResponse(
            question=payload.question,
            answer=answer,
            answer_html=report_export.markdown_to_html(answer),
            citations=citations,
            grounded=False,
            model=settings.GEMINI_MODEL,
        )

    context_chunks = [c.model_dump() for c in citations]
    try:
        answer = await ai_service.answer_portfolio_question(
            payload.question, context_chunks
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)

    return PortfolioAskResponse(
        question=payload.question,
        answer=answer,
        answer_html=report_export.markdown_to_html(answer),
        citations=citations,
        grounded=True,
        model=settings.GEMINI_MODEL,
    )

"""AI-assist API (Google Gemini).

Mounted at ``/api/v1/ai`` behind ``enforce_org_access``. Endpoints return
*suggestions* for human review; nothing is auto-committed.

Gating:

* ``POST /ai/leases/parse`` — **basic lease detail ingestion**, available on all
  tiers (not gated by ``ai_assist``).
* ``POST /ai/ap/parse`` — **vendor bill / invoice ingestion**, all tiers.
* ``POST /ai/insurance/parse`` — **certificate-of-insurance ingestion**, all tiers.
* ``POST /ai/hvac-contracts/parse`` — **HVAC contract ingestion**, all tiers.
* ``POST /ai/leases/{lease_id}/abstract/suggest`` — Pro+ (``ai_assist``).
* ``POST /ai/tickets/triage`` — **maintenance ticket triage**, Pro+ (``ai_assist``).
* ``POST /ai/tickets/similar`` — **duplicate ticket detection**, Pro+ (``ai_assist``).
* ``POST /ai/tickets/draft-from-email`` — **email → ticket draft**, Pro+ (``ai_assist``).
* ``POST /ai/assistant/query`` — **portfolio Q&A (RAG)**, Pro+ (``ai_assist``).
* ``POST /ai/assistant/reindex`` — **rebuild the knowledge index**, Pro+ (``ai_assist``).
* ``POST /ai/reports/summary`` — Pro+ (``ai_assist``).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_feature
from app.config import settings
from app.database import get_db
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
from app.models.organization import Organization
from app.models.user import User
from app.models.vendor import Vendor
from app.services import (
    ai_service,
    document_extraction,
    entitlements as ent,
    knowledge_service,
    report_export,
    usage_service,
)
from app.services.lease_abstract_catalog import CLAUSE_CATEGORIES

router = APIRouter()


# ── Token budget + usage instrumentation ──────────────────────────────────────

# Limit keys (in entitlements.py) that cap monthly AI token consumption.
_INPUT_TOKEN_LIMIT_KEY = "monthly_ai_input_tokens"
_OUTPUT_TOKEN_LIMIT_KEY = "monthly_ai_output_tokens"


async def reset_ai_usage() -> None:
    """Router dependency: start a fresh per-request token accumulator.

    Runs before the path operation (and therefore before any ``_generate``
    call) so :func:`ai_service.collect_token_usage` returns only the tokens this
    request spent.
    """
    ai_service.reset_token_usage()


async def _org_for_user(db: AsyncSession, user: User) -> Organization | None:
    if user.organization_id is None:
        return None
    result = await db.execute(
        select(Organization).where(Organization.id == user.organization_id)
    )
    return result.scalar_one_or_none()


async def enforce_ai_token_budget(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Reject AI requests once the org has exhausted its monthly token budget.

    Super-admins and org-less internal accounts bypass the check. The current
    period's accumulated input/output tokens are compared against the org's
    tier limits (``None`` == unlimited); exceeding either returns HTTP 429 with
    an upgrade prompt, mirroring the ``require_feature`` 402 pattern.
    """
    if user.is_super_admin or user.organization_id is None:
        return
    org = await _org_for_user(db, user)
    if org is None:
        return

    input_limit = ent.get_limit(org, _INPUT_TOKEN_LIMIT_KEY)
    output_limit = ent.get_limit(org, _OUTPUT_TOKEN_LIMIT_KEY)
    if input_limit is None and output_limit is None:
        return  # unlimited on both axes

    used_input, used_output = await usage_service.org_period_tokens(db, org.id)
    over_input = input_limit is not None and used_input >= input_limit
    over_output = output_limit is not None and used_output >= output_limit
    if over_input or over_output:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Monthly AI token limit reached for your "
                f"{org.plan} plan. Upgrade your plan or wait until next month "
                "to continue using AI features."
            ),
        )


async def _log_ai_usage(
    db: AsyncSession,
    org_id,
    feature: str,
    quantity: int = 1,
    meta: dict | None = None,
) -> None:
    """Best-effort: record a usage event including AI token consumption.

    Token counts are pulled from the per-request accumulator populated by
    :func:`ai_service._generate` / :func:`ai_service.embed_texts`.
    """
    input_tokens, output_tokens = ai_service.collect_token_usage()
    await usage_service.record_event(
        db,
        org_id,
        feature,
        quantity=quantity,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        meta=meta,
    )


# ── Schemas ───────────────────────────────────────────────────────────────────

class AIStatusResponse(BaseModel):
    configured: bool
    model: str
    # Monthly AI token budget for the caller's org (None == unlimited).
    period: str
    input_tokens_used: int
    output_tokens_used: int
    input_token_limit: int | None
    output_token_limit: int | None
    token_limit_reached: bool


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
    narrative_html: str
    data: dict
    model: str


class SummaryExportRequest(BaseModel):
    narrative: str = Field(min_length=1)
    period_label: str = "Operations Briefing"
    format: str = "pdf"  # 'pdf' | 'docx'


class AssistantQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=20)


class AssistantCitation(BaseModel):
    index: int
    source_type: str
    source_id: str | None = None
    title: str
    reference: str | None = None
    snippet: str
    score: float


class AssistantQueryResponse(BaseModel):
    answer: str
    citations: list[AssistantCitation]
    mode: str  # 'semantic' | 'keyword'
    model: str


class AssistantReindexResponse(BaseModel):
    indexed: int


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
async def ai_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Report whether AI assist is configured and the org's token headroom."""
    period = usage_service.current_period()
    used_input = used_output = 0
    input_limit: int | None = None
    output_limit: int | None = None
    reached = False

    org = await _org_for_user(db, current_user)
    if org is not None and not current_user.is_super_admin:
        input_limit = ent.get_limit(org, _INPUT_TOKEN_LIMIT_KEY)
        output_limit = ent.get_limit(org, _OUTPUT_TOKEN_LIMIT_KEY)
        used_input, used_output = await usage_service.org_period_tokens(db, org.id)
        reached = (input_limit is not None and used_input >= input_limit) or (
            output_limit is not None and used_output >= output_limit
        )

    return AIStatusResponse(
        configured=ai_service.is_configured(),
        model=settings.GEMINI_MODEL,
        period=period,
        input_tokens_used=used_input,
        output_tokens_used=used_output,
        input_token_limit=input_limit,
        output_token_limit=output_limit,
        token_limit_reached=reached,
    )


# ── Basic lease ingestion (all tiers) ─────────────────────────────────────────

@router.post(
    "/leases/parse",
    response_model=LeaseParseResponse,
    dependencies=[Depends(enforce_ai_token_budget)],
)
async def parse_lease(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
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
    await _log_ai_usage(db, current_user.organization_id, "ai_lease_parse")
    return LeaseParseResponse(suggested=suggested, model=settings.GEMINI_MODEL)


# ── Document extraction for other entities (all tiers, like lease parse) ──────

class DocumentParseResponse(BaseModel):
    suggested: dict
    model: str


async def _parse_document_with(
    file: UploadFile,
    parser,
    db: AsyncSession,
    org_id,
    feature: str,
) -> DocumentParseResponse:
    """Shared body for the per-entity document-extraction endpoints."""
    content, mime_type = await _read_document(file)
    text_content = _maybe_extract_text(file.filename, content)
    try:
        suggested = await parser(content, mime_type, text_content=text_content)
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    await _log_ai_usage(db, org_id, feature)
    return DocumentParseResponse(suggested=suggested, model=settings.GEMINI_MODEL)


@router.post(
    "/ap/parse",
    response_model=DocumentParseResponse,
    dependencies=[Depends(enforce_ai_token_budget)],
)
async def parse_vendor_bill(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extract suggested vendor-bill header fields from an uploaded invoice."""
    return await _parse_document_with(
        file, ai_service.parse_vendor_bill_document, db,
        current_user.organization_id, "ai_ap_parse",
    )


@router.post(
    "/insurance/parse",
    response_model=DocumentParseResponse,
    dependencies=[Depends(enforce_ai_token_budget)],
)
async def parse_insurance(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extract suggested certificate-of-insurance fields from an uploaded document."""
    return await _parse_document_with(
        file, ai_service.parse_insurance_certificate, db,
        current_user.organization_id, "ai_insurance_parse",
    )


@router.post(
    "/hvac-contracts/parse",
    response_model=DocumentParseResponse,
    dependencies=[Depends(enforce_ai_token_budget)],
)
async def parse_hvac_contract(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extract suggested HVAC-contract fields from an uploaded document."""
    return await _parse_document_with(
        file, ai_service.parse_hvac_contract, db,
        current_user.organization_id, "ai_hvac_parse",
    )


# ── Maintenance ticket intelligence (Pro+) ────────────────────────────────────

class TicketTriageRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    description: str = ""


class TicketTriageSuggestion(BaseModel):
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    priority: str | None = None
    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = None
    reasoning: str | None = None


class TicketTriageResponse(BaseModel):
    suggested: TicketTriageSuggestion
    model: str


class SimilarTicketsRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    description: str = ""
    exclude_id: uuid.UUID | None = None
    limit: int = Field(default=5, ge=1, le=20)


class SimilarTicketMatch(BaseModel):
    id: uuid.UUID
    subject: str
    status: str
    priority: str
    score: float
    created_at: datetime


class SimilarTicketsResponse(BaseModel):
    matches: list[SimilarTicketMatch]
    mode: str  # 'semantic' | 'keyword'


class TicketEmailDraftRequest(BaseModel):
    email_text: str = Field(min_length=1)


class TicketEmailDraftResponse(BaseModel):
    suggested: dict
    model: str


# Candidate open tickets considered for duplicate detection per request.
_SIMILAR_CANDIDATE_LIMIT = 200
# Minimum similarity for a match to surface (semantic / keyword respectively).
_SEMANTIC_SIMILAR_THRESHOLD = 0.78
_KEYWORD_SIMILAR_THRESHOLD = 0.3


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _keyword_tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(t) > 2}


@router.post(
    "/tickets/triage",
    response_model=TicketTriageResponse,
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
)
async def triage_ticket(
    payload: TicketTriageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest a category, priority, and vendor for a maintenance request.

    The model is constrained to the org's existing categories and vendors; the
    returned names are mapped back onto ids for the form to apply after review.
    """
    org_id = current_user.organization_id
    categories = (
        await db.execute(
            select(TicketCategory).where(TicketCategory.organization_id == org_id)
        )
    ).scalars().all()
    vendors = (
        await db.execute(
            select(Vendor).where(
                Vendor.organization_id == org_id, Vendor.is_deleted.is_(False)
            )
        )
    ).scalars().all()

    try:
        result = await ai_service.triage_ticket(
            payload.subject,
            payload.description,
            categories=[c.name for c in categories],
            vendors=[{"name": v.company_name, "services": v.services} for v in vendors],
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)

    suggested = _map_triage_result(result, categories, vendors)
    await _log_ai_usage(db, current_user.organization_id, "ai_triage")
    return TicketTriageResponse(suggested=suggested, model=settings.GEMINI_MODEL)


def _map_triage_result(result: dict, categories, vendors) -> TicketTriageSuggestion:
    """Resolve the model's suggested category/vendor names back onto ids."""
    cat_name = (result.get("category") or "").strip() or None
    vendor_name = (result.get("vendor") or "").strip() or None
    priority = (result.get("priority") or "").strip().lower() or None
    if priority not in {"low", "medium", "high"}:
        priority = None

    category_id = None
    matched_cat_name = None
    if cat_name:
        for c in categories:
            if c.name.strip().lower() == cat_name.lower():
                category_id, matched_cat_name = c.id, c.name
                break

    vendor_id = None
    matched_vendor_name = None
    if vendor_name:
        for v in vendors:
            if v.company_name.strip().lower() == vendor_name.lower():
                vendor_id, matched_vendor_name = v.id, v.company_name
                break

    return TicketTriageSuggestion(
        category_id=category_id,
        category_name=matched_cat_name,
        priority=priority,
        vendor_id=vendor_id,
        vendor_name=matched_vendor_name,
        reasoning=(result.get("reasoning") or None),
    )


@router.post(
    "/tickets/similar",
    response_model=SimilarTicketsResponse,
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
)
async def similar_tickets(
    payload: SimilarTicketsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Surface open tickets similar to a draft, to catch duplicates on intake.

    Uses Gemini embeddings + cosine similarity when configured, and degrades to a
    keyword token-overlap match when no API key is set so the feature still works.
    """
    stmt = (
        select(MaintenanceTicket)
        .where(
            MaintenanceTicket.organization_id == current_user.organization_id,
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.status.in_(["open", "in_progress"]),
        )
        .order_by(MaintenanceTicket.created_at.desc())
        .limit(_SIMILAR_CANDIDATE_LIMIT)
    )
    if payload.exclude_id is not None:
        stmt = stmt.where(MaintenanceTicket.id != payload.exclude_id)
    candidates = (await db.execute(stmt)).scalars().all()
    if not candidates:
        return SimilarTicketsResponse(matches=[], mode="keyword")

    query_text = f"{payload.subject}\n\n{payload.description}".strip()
    cand_texts = [f"{t.subject}\n\n{t.description}".strip() for t in candidates]

    scored: list[tuple[float, MaintenanceTicket]] = []
    mode = "keyword"
    if ai_service.is_configured():
        try:
            vectors = await ai_service.embed_texts([query_text, *cand_texts])
            query_vec, cand_vecs = vectors[0], vectors[1:]
            for ticket, vec in zip(candidates, cand_vecs):
                score = _cosine(query_vec, vec)
                if score >= _SEMANTIC_SIMILAR_THRESHOLD:
                    scored.append((score, ticket))
            mode = "semantic"
        except ai_service.AIError:
            scored = []  # fall through to keyword matching below

    if mode == "keyword":
        query_tokens = _keyword_tokens(query_text)
        if query_tokens:
            for ticket, text in zip(candidates, cand_texts):
                cand_tokens = _keyword_tokens(text)
                if not cand_tokens:
                    continue
                overlap = len(query_tokens & cand_tokens)
                score = overlap / len(query_tokens | cand_tokens)
                if score >= _KEYWORD_SIMILAR_THRESHOLD:
                    scored.append((score, ticket))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    matches = [
        SimilarTicketMatch(
            id=t.id,
            subject=t.subject,
            status=t.status,
            priority=t.priority,
            score=round(score, 4),
            created_at=t.created_at,
        )
        for score, t in scored[: payload.limit]
    ]
    await _log_ai_usage(db, current_user.organization_id, "ai_similar")
    return SimilarTicketsResponse(matches=matches, mode=mode)


@router.post(
    "/tickets/draft-from-email",
    response_model=TicketEmailDraftResponse,
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
)
async def draft_ticket_from_email(
    payload: TicketEmailDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Draft structured ticket fields from a free-text request email."""
    categories = (
        await db.execute(
            select(TicketCategory).where(
                TicketCategory.organization_id == current_user.organization_id
            )
        )
    ).scalars().all()
    try:
        suggested = await ai_service.draft_ticket_from_email(
            payload.email_text, categories=[c.name for c in categories]
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    await _log_ai_usage(db, current_user.organization_id, "ai_draft")
    return TicketEmailDraftResponse(suggested=suggested, model=settings.GEMINI_MODEL)


# ── Lease abstract suggestions (Pro+) ─────────────────────────────────────────

@router.post(
    "/leases/{lease_id}/abstract/suggest",
    response_model=AbstractSuggestResponse,
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
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
    await _log_ai_usage(db, current_user.organization_id, "ai_abstract")
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
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
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
    await _log_ai_usage(db, current_user.organization_id, "ai_summary")
    return SummaryResponse(
        period=period,
        period_label=period_label,
        narrative=narrative,
        narrative_html=report_export.markdown_to_html(narrative),
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


# ── Portfolio assistant (RAG Q&A, Pro+) ───────────────────────────────────────

# Cap the length of the citation preview returned to the client.
_CITATION_SNIPPET_CHARS = 320


def _citation_snippet(content: str) -> str:
    text = " ".join((content or "").split())
    if len(text) > _CITATION_SNIPPET_CHARS:
        return text[:_CITATION_SNIPPET_CHARS].rstrip() + "…"
    return text


@router.post(
    "/assistant/query",
    response_model=AssistantQueryResponse,
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
)
async def assistant_query(
    payload: AssistantQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Answer a natural-language question about the org's portfolio (RAG).

    Retrieves the most relevant chunks from the generalized knowledge index and
    the lease-document index (organization-scoped), then asks Gemini to answer
    grounded in those passages with inline citations. Degrades to a 503 when AI
    is not configured (generation requires the model), and returns an honest
    "not enough information" style answer when retrieval finds nothing.
    """
    org_id = current_user.organization_id
    chunks = await knowledge_service.retrieve(
        db, organization_id=org_id, query=payload.question, limit=payload.limit
    )

    try:
        answer = await ai_service.answer_portfolio_question(payload.question, chunks)
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)

    await _log_ai_usage(db, current_user.organization_id, "ai_assistant")
    mode = chunks[0]["match_type"] if chunks else "semantic"
    citations = [
        AssistantCitation(
            index=idx,
            source_type=chunk["source_type"],
            source_id=chunk.get("source_id"),
            title=chunk["title"],
            reference=chunk.get("reference"),
            snippet=_citation_snippet(chunk.get("content", "")),
            score=chunk.get("score", 0.0),
        )
        for idx, chunk in enumerate(chunks, start=1)
    ]
    return AssistantQueryResponse(
        answer=answer, citations=citations, mode=mode, model=settings.GEMINI_MODEL
    )


@router.post(
    "/assistant/reindex",
    response_model=AssistantReindexResponse,
    dependencies=[Depends(require_feature("ai_assist")), Depends(enforce_ai_token_budget)],
)
async def assistant_reindex(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rebuild this organization's portfolio knowledge index on demand.

    The index is also refreshed nightly by the scheduler; this endpoint lets an
    operator force an immediate rebuild after bulk edits. Works without AI
    configured (chunks are stored keyword-only in that case).
    """
    try:
        indexed = await knowledge_service.reindex_organization(
            db, current_user.organization_id
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)
    await _log_ai_usage(db, current_user.organization_id, "ai_reindex")
    return AssistantReindexResponse(indexed=indexed)


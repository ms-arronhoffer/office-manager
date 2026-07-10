"""CAM reconciliation API router (Phase 3) — `/api/v1/cam`.

US-commercial common-area-maintenance reconciliation. All endpoints are gated to
the ``admin`` and ``accountant`` roles so finance data stays with finance staff.

Workflow:
  1. ``POST /reconciliations`` computes a draft statement for a lease-year from
     supplied expense lines (or the lease-year's operating expenses) and terms.
  2. ``PATCH`` recomputes a draft as terms/lines change; ``DELETE`` removes it.
  3. ``POST /{id}/finalize`` locks the statement (immutable, audit-grade).
  4. ``POST /{id}/post-to-gl`` records the true-up or credit in the general
     ledger and links the journal entry back to the statement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_feature, require_role
from app.config import settings
from app.database import get_db
from app.models.cam_reconciliation import CamReconciliation
from app.models.lease import Lease
from app.models.lease_abstract import LeaseAbstractClause
from app.models.user import User
from app.services import ai_service, cam_service
from app.services.cam_service import CamError
from app.services.lease_abstract_catalog import CATEGORY_BY_KEY
from app.utils.tenant_scope import load_or_404

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")

# Abstracted clause categories that constrain what CAM may recover. These are
# fed to the AI reviewer so it can flag charges outside the lease-permitted
# categories or in conflict with recovery terms (caps, gross-up, base year).
CAM_REVIEW_CLAUSE_KEYS = (
    "expense_recoverables",
    "expense_schedule",
    "cpi",
    "improvements",
    "lease_audit_rights",
    "exclusivity_permitted_use",
    "utilities_services",
    "maintenance_repairs",
)


# ─── Schemas ────────────────────────────────────────────────────────────────

class CamLineInput(BaseModel):
    category: str
    actual_amount: Decimal
    controllable: bool | None = None
    gross_up_eligible: bool | None = None


class CamReconciliationCreate(BaseModel):
    lease_id: uuid.UUID
    year: int
    # Recovery terms (all optional; share may be derived from square footage).
    pro_rata_share: Decimal | None = None
    rentable_sqft: Decimal | None = None
    building_sqft: Decimal | None = None
    gross_up_percent: Decimal | None = None
    occupancy_percent: Decimal | None = None
    base_year_amount: Decimal | None = None
    expense_stop_psf: Decimal | None = None
    cap_percent: Decimal | None = None
    cap_type: str | None = None
    cap_base_year: int | None = None
    cap_base_amount: Decimal | None = None
    estimated_paid: Decimal = Decimal("0")
    notes: str | None = None
    # When omitted, lines are seeded from the lease-year's operating expenses.
    lines: list[CamLineInput] | None = None


class CamReconciliationUpdate(BaseModel):
    pro_rata_share: Decimal | None = None
    rentable_sqft: Decimal | None = None
    building_sqft: Decimal | None = None
    gross_up_percent: Decimal | None = None
    occupancy_percent: Decimal | None = None
    base_year_amount: Decimal | None = None
    expense_stop_psf: Decimal | None = None
    cap_percent: Decimal | None = None
    cap_type: str | None = None
    cap_base_year: int | None = None
    cap_base_amount: Decimal | None = None
    estimated_paid: Decimal | None = None
    notes: str | None = None
    lines: list[CamLineInput] | None = None


class CamLineResponse(BaseModel):
    id: uuid.UUID
    line_number: int
    category: str
    controllable: bool
    gross_up_eligible: bool
    actual_amount: Decimal
    grossed_up_amount: Decimal

    model_config = {"from_attributes": True}


class CamReconciliationResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    lease_id: uuid.UUID
    year: int
    pro_rata_share: Decimal | None
    rentable_sqft: Decimal | None
    building_sqft: Decimal | None
    gross_up_percent: Decimal | None
    occupancy_percent: Decimal | None
    base_year_amount: Decimal | None
    expense_stop_psf: Decimal | None
    cap_percent: Decimal | None
    cap_type: str | None
    cap_base_year: int | None
    cap_base_amount: Decimal | None
    estimated_paid: Decimal
    total_pool: Decimal
    controllable_pool: Decimal
    noncontrollable_pool: Decimal
    tenant_share_amount: Decimal
    cap_applied: Decimal
    offset_amount: Decimal
    recoverable_amount: Decimal
    balance_due: Decimal
    status: str
    finalized_at: datetime | None
    journal_entry_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[CamLineResponse]

    model_config = {"from_attributes": True}


class CamAnomaly(BaseModel):
    category: str = ""
    anomaly_type: str  # 'year_over_year' | 'not_permitted' | 'cap_or_term' | 'other'
    severity: str  # 'high' | 'medium' | 'low'
    message: str
    recommendation: str = ""


class CamReviewResponse(BaseModel):
    reconciliation_id: uuid.UUID
    year: int
    prior_year: int | None
    summary: str
    anomalies: list[CamAnomaly] = Field(default_factory=list)
    model: str


# ─── Helpers ────────────────────────────────────────────────────────────────

# Term fields carried verbatim from the request onto the reconciliation record.
_TERM_FIELDS = (
    "pro_rata_share",
    "rentable_sqft",
    "building_sqft",
    "gross_up_percent",
    "occupancy_percent",
    "base_year_amount",
    "expense_stop_psf",
    "cap_percent",
    "cap_type",
    "cap_base_year",
    "cap_base_amount",
    "estimated_paid",
    "notes",
)


def _build_compute_inputs(recon: CamReconciliation, line_dicts: list[dict]) -> dict:
    """Resolve the pro-rata share and assemble compute-engine keyword inputs."""
    share = cam_service.resolve_pro_rata_share(
        recon.pro_rata_share, recon.rentable_sqft, recon.building_sqft
    )
    return {
        "lines": line_dicts,
        "pro_rata_share": share,
        "year": recon.year,
        "gross_up_percent": recon.gross_up_percent,
        "occupancy_percent": recon.occupancy_percent,
        "base_year_amount": recon.base_year_amount,
        "expense_stop_psf": recon.expense_stop_psf,
        "rentable_sqft": recon.rentable_sqft,
        "cap_percent": recon.cap_percent,
        "cap_type": recon.cap_type,
        "cap_base_year": recon.cap_base_year,
        "cap_base_amount": recon.cap_base_amount,
        "estimated_paid": recon.estimated_paid or 0,
    }


def _normalize_lines(line_inputs: list[CamLineInput]) -> list[dict]:
    """Apply category defaults to any line flags left unset by the caller."""
    out: list[dict] = []
    for line in line_inputs:
        controllable, gross_up_eligible = cam_service.default_line_flags(line.category)
        out.append(
            {
                "category": line.category,
                "actual_amount": line.actual_amount,
                "controllable": (
                    controllable if line.controllable is None else line.controllable
                ),
                "gross_up_eligible": (
                    gross_up_eligible
                    if line.gross_up_eligible is None
                    else line.gross_up_eligible
                ),
            }
        )
    return out


async def _load_with_lines(
    db: AsyncSession, recon_id: uuid.UUID, org_id: uuid.UUID | None
) -> CamReconciliation:
    recon = await load_or_404(
        db,
        CamReconciliation,
        recon_id,
        org_id,
        detail="Reconciliation not found",
    )
    await db.refresh(recon, attribute_names=["lines"])
    return recon


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/reconciliations", response_model=list[CamReconciliationResponse])
async def list_reconciliations(
    lease_id: uuid.UUID | None = Query(default=None),
    year: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(CamReconciliation)
        .where(CamReconciliation.organization_id == current_user.organization_id)
        .options(selectinload(CamReconciliation.lines))
        .order_by(CamReconciliation.year.desc(), CamReconciliation.created_at.desc())
    )
    if lease_id:
        stmt = stmt.where(CamReconciliation.lease_id == lease_id)
    if year is not None:
        stmt = stmt.where(CamReconciliation.year == year)
    result = await db.execute(stmt)
    return [
        CamReconciliationResponse.model_validate(r)
        for r in result.scalars().unique().all()
    ]


@router.get("/reconciliations/{recon_id}", response_model=CamReconciliationResponse)
async def get_reconciliation(
    recon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    recon = (
        await db.execute(
            select(CamReconciliation)
            .where(
                CamReconciliation.id == recon_id,
                CamReconciliation.organization_id == current_user.organization_id,
            )
            .options(selectinload(CamReconciliation.lines))
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")
    return CamReconciliationResponse.model_validate(recon)


@router.post(
    "/reconciliations",
    response_model=CamReconciliationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reconciliation(
    payload: CamReconciliationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Compute and persist a draft reconciliation for a lease-year."""
    lease = (
        await db.execute(
            select(Lease).where(
                Lease.id == payload.lease_id,
                Lease.organization_id == current_user.organization_id,
                Lease.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    existing = (
        await db.execute(
            select(CamReconciliation).where(
                CamReconciliation.organization_id == current_user.organization_id,
                CamReconciliation.lease_id == payload.lease_id,
                CamReconciliation.year == payload.year,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A reconciliation already exists for this lease and year {payload.year}.",
        )

    # Resolve lines: explicit input, else seed from operating expenses.
    if payload.lines is not None:
        line_dicts = _normalize_lines(payload.lines)
    else:
        line_dicts = await cam_service.lines_from_operating_expenses(
            db, current_user.organization_id, payload.lease_id, payload.year
        )
    if not line_dicts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No expense lines supplied and no operating expenses found for this lease-year.",
        )

    recon = CamReconciliation(
        organization_id=current_user.organization_id,
        lease_id=payload.lease_id,
        year=payload.year,
        status="draft",
    )
    for field in _TERM_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(recon, field, value)

    try:
        result = cam_service.compute_cam_reconciliation(
            **_build_compute_inputs(recon, line_dicts)
        )
    except CamError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    cam_service.apply_computation(recon, result)
    db.add(recon)
    await db.commit()
    recon = await _load_with_lines(db, recon.id, current_user.organization_id)
    return CamReconciliationResponse.model_validate(recon)


@router.patch("/reconciliations/{recon_id}", response_model=CamReconciliationResponse)
async def update_reconciliation(
    recon_id: uuid.UUID,
    payload: CamReconciliationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Update a draft reconciliation's terms/lines and recompute."""
    recon = (
        await db.execute(
            select(CamReconciliation)
            .where(
                CamReconciliation.id == recon_id,
                CamReconciliation.organization_id == current_user.organization_id,
            )
            .options(selectinload(CamReconciliation.lines))
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")
    if recon.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finalized reconciliation cannot be modified.",
        )

    data = payload.model_dump(exclude_unset=True)
    for field in _TERM_FIELDS:
        if field in data:
            setattr(recon, field, data[field])

    if payload.lines is not None:
        line_dicts = _normalize_lines(payload.lines)
    else:
        line_dicts = [
            {
                "category": line.category,
                "actual_amount": line.actual_amount,
                "controllable": line.controllable,
                "gross_up_eligible": line.gross_up_eligible,
            }
            for line in recon.lines
        ]

    try:
        result = cam_service.compute_cam_reconciliation(
            **_build_compute_inputs(recon, line_dicts)
        )
    except CamError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    cam_service.apply_computation(recon, result)
    await db.commit()
    recon = await _load_with_lines(db, recon.id, current_user.organization_id)
    return CamReconciliationResponse.model_validate(recon)


@router.delete("/reconciliations/{recon_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reconciliation(
    recon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    recon = (
        await db.execute(
            select(CamReconciliation).where(
                CamReconciliation.id == recon_id,
                CamReconciliation.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")
    if recon.status == "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A finalized reconciliation cannot be deleted.",
        )
    await db.delete(recon)
    await db.commit()


@router.post(
    "/reconciliations/{recon_id}/finalize",
    response_model=CamReconciliationResponse,
)
async def finalize_reconciliation(
    recon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Lock a reconciliation so its statement becomes immutable."""
    recon = (
        await db.execute(
            select(CamReconciliation)
            .where(
                CamReconciliation.id == recon_id,
                CamReconciliation.organization_id == current_user.organization_id,
            )
            .options(selectinload(CamReconciliation.lines))
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")
    if recon.status == "finalized":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reconciliation is already finalized."
        )
    recon.status = "finalized"
    recon.finalized_at = datetime.now(timezone.utc)
    recon.finalized_by_id = current_user.id
    await db.commit()
    recon = await _load_with_lines(db, recon.id, current_user.organization_id)
    return CamReconciliationResponse.model_validate(recon)


@router.post("/reconciliations/{recon_id}/post-to-gl")
async def post_reconciliation(
    recon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Post a finalized reconciliation's true-up or credit into the GL."""
    recon = (
        await db.execute(
            select(CamReconciliation).where(
                CamReconciliation.id == recon_id,
                CamReconciliation.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")

    try:
        entry = await cam_service.post_reconciliation_to_gl(
            db, current_user.organization_id, recon, posted_by_id=current_user.id
        )
    except CamError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return {
        "reconciliation_id": recon.id,
        "balance_due": recon.balance_due,
        "journal_entry_id": entry.id if entry else None,
        "posted": entry is not None,
    }


def _review_lines(recon: CamReconciliation) -> list[dict]:
    """Project a reconciliation's lines into the shape sent to the AI reviewer."""
    return [
        {
            "category": line.category,
            "controllable": line.controllable,
            "gross_up_eligible": line.gross_up_eligible,
            "actual_amount": line.actual_amount,
            "grossed_up_amount": line.grossed_up_amount,
        }
        for line in sorted(recon.lines, key=lambda r: r.line_number)
    ]


def _ai_error_response(exc: ai_service.AIError) -> HTTPException:
    if isinstance(exc, ai_service.AIUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post(
    "/reconciliations/{recon_id}/ai-review",
    response_model=CamReviewResponse,
    dependencies=[Depends(require_feature("ai_assist"))],
)
async def ai_review_reconciliation(
    recon_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Flag anomalous CAM line items for human review.

    Cross-references the prior year's reconciliation (year-over-year variance)
    and the lease's abstracted recovery clauses (charges outside lease-permitted
    categories or in conflict with caps/gross-up/base-year terms). Findings are
    advisory only — nothing is changed on the statement.
    """
    org_id = current_user.organization_id
    recon = (
        await db.execute(
            select(CamReconciliation)
            .where(
                CamReconciliation.id == recon_id,
                CamReconciliation.organization_id == org_id,
            )
            .options(selectinload(CamReconciliation.lines))
        )
    ).scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")

    # Prior-year reconciliation for the same lease (year-over-year variance).
    prior = (
        await db.execute(
            select(CamReconciliation)
            .where(
                CamReconciliation.organization_id == org_id,
                CamReconciliation.lease_id == recon.lease_id,
                CamReconciliation.year == recon.year - 1,
            )
            .options(selectinload(CamReconciliation.lines))
        )
    ).scalar_one_or_none()

    # Abstracted lease clauses that constrain recoverable expenses.
    clause_rows = (
        await db.execute(
            select(LeaseAbstractClause).where(
                LeaseAbstractClause.lease_id == recon.lease_id,
                LeaseAbstractClause.category_key.in_(CAM_REVIEW_CLAUSE_KEYS),
            )
        )
    ).scalars().all()
    lease_clauses: dict = {}
    for clause in clause_rows:
        category = CATEGORY_BY_KEY.get(clause.category_key)
        if not category:
            continue
        content = {
            k: v for k, v in (clause.content or {}).items() if v not in (None, "", [], {})
        }
        if not content and not (clause.notes or "").strip():
            continue
        entry: dict = {}
        if content:
            entry["content"] = content
        if (clause.notes or "").strip():
            entry["notes"] = clause.notes
        lease_clauses[category["name"]] = entry

    try:
        review = await ai_service.review_cam_reconciliation(
            year=recon.year,
            lines=_review_lines(recon),
            prior_year=prior.year if prior else None,
            prior_lines=_review_lines(prior) if prior else None,
            lease_clauses=lease_clauses,
        )
    except ai_service.AIError as exc:
        raise _ai_error_response(exc)

    return CamReviewResponse(
        reconciliation_id=recon.id,
        year=recon.year,
        prior_year=prior.year if prior else None,
        summary=review["summary"],
        anomalies=[CamAnomaly(**a) for a in review["anomalies"]],
        model=settings.GEMINI_MODEL,
    )

"""Lease Abstract API.

Serves the clause-category catalog merged with stored content for a lease, and
upserts per-clause content/status/notes. Mounted under ``/api/v1/leases`` so all
routes are scoped by ``{lease_id}``.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.lease import Lease
from app.models.lease_abstract import LeaseAbstractClause
from app.models.user import User
from app.schemas.lease_abstract import (
    AbstractClause,
    AbstractClauseUpdate,
    AbstractSummary,
    LeaseAbstractResponse,
)
from app.services.activity_service import log_activity
from app.services.lease_abstract_catalog import (
    CATEGORY_BY_KEY,
    CLAUSE_CATEGORIES,
    CLAUSE_STATUSES,
    derive_status,
    get_category,
)

router = APIRouter()


async def _get_lease(lease_id: uuid.UUID, db: AsyncSession, current_user: User) -> Lease:
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
    return lease


def _clause_out(category: dict, clause: LeaseAbstractClause | None) -> AbstractClause:
    return AbstractClause(
        category_key=category["key"],
        name=category["name"],
        group=category["group"],
        order=category["order"],
        fields=category["fields"],
        status=clause.status if clause else "needs_content",
        content=clause.content if clause else None,
        notes=clause.notes if clause else None,
        updated_at=clause.updated_at if clause else None,
    )


def _summarize(clauses: list[AbstractClause]) -> AbstractSummary:
    counts = {"contains_content": 0, "needs_content": 0, "incomplete": 0}
    for c in clauses:
        counts[c.status] = counts.get(c.status, 0) + 1
    return AbstractSummary(
        total=len(clauses),
        contains_content=counts["contains_content"],
        needs_content=counts["needs_content"],
        incomplete=counts["incomplete"],
    )


@router.get("/{lease_id}/abstract", response_model=LeaseAbstractResponse)
async def get_lease_abstract(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return every clause category merged with stored content + a roll-up."""
    await _get_lease(lease_id, db, current_user)

    result = await db.execute(
        select(LeaseAbstractClause).where(LeaseAbstractClause.lease_id == lease_id)
    )
    stored = {c.category_key: c for c in result.scalars().all()}

    ordered = sorted(CLAUSE_CATEGORIES, key=lambda c: (c["group"], c["order"], c["name"]))
    clauses = [_clause_out(cat, stored.get(cat["key"])) for cat in ordered]
    return LeaseAbstractResponse(
        lease_id=lease_id,
        clauses=clauses,
        summary=_summarize(clauses),
    )


@router.get("/{lease_id}/abstract/{category_key}", response_model=AbstractClause)
async def get_lease_abstract_clause(
    lease_id: uuid.UUID,
    category_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_lease(lease_id, db, current_user)
    category = get_category(category_key)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown clause category")

    result = await db.execute(
        select(LeaseAbstractClause).where(
            LeaseAbstractClause.lease_id == lease_id,
            LeaseAbstractClause.category_key == category_key,
        )
    )
    return _clause_out(category, result.scalar_one_or_none())


@router.put("/{lease_id}/abstract/{category_key}", response_model=AbstractClause)
async def upsert_lease_abstract_clause(
    lease_id: uuid.UUID,
    category_key: str,
    payload: AbstractClauseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    lease = await _get_lease(lease_id, db, current_user)
    category = get_category(category_key)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown clause category")

    if payload.status is not None and payload.status not in CLAUSE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    # Reject content keys that are not part of this category's schema.
    if payload.content is not None:
        valid_keys = {f["key"] for f in category["fields"]}
        unknown = set(payload.content) - valid_keys
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown field(s) for category: {', '.join(sorted(unknown))}",
            )

    result = await db.execute(
        select(LeaseAbstractClause).where(
            LeaseAbstractClause.lease_id == lease_id,
            LeaseAbstractClause.category_key == category_key,
        )
    )
    clause = result.scalar_one_or_none()
    if clause is None:
        clause = LeaseAbstractClause(
            lease_id=lease_id,
            organization_id=lease.organization_id,
            category_key=category_key,
        )
        db.add(clause)

    clause.content = payload.content
    clause.notes = payload.notes
    clause.status = payload.status or derive_status(category, payload.content, payload.notes)
    clause.updated_at = _utcnow()

    await db.commit()
    await db.refresh(clause)

    await log_activity(
        db,
        user=current_user,
        action="updated",
        entity_type="lease_abstract",
        entity_id=lease_id,
        entity_label=f"{lease.lease_name} — {category['name']}",
    )

    return _clause_out(CATEGORY_BY_KEY[category_key], clause)

import csv
import io
import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.activity_log import ActivityLog
from app.models.organization import Organization
from app.models.user import User
from app.schemas.activity_log import ActivityLogResponse
from app.schemas.common import PaginatedResponse
from app.services import entitlements as ent

router = APIRouter()


async def _retention_cutoff(db: AsyncSession, current_user: User) -> datetime | None:
    """Earliest visible audit timestamp for the user's org, per plan retention.

    Returns ``None`` when retention is unlimited (or no org / super-admin).
    """
    if current_user.organization_id is None:
        return None
    org = (
        await db.execute(select(Organization).where(Organization.id == current_user.organization_id))
    ).scalar_one_or_none()
    if org is None:
        return None
    days = ent.get_limit(org, "audit_retention_days")
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _apply_report_filters(
    stmt,
    *,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    action: str | None,
    user_id: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    search: str | None,
):
    """Shared filter logic for both the JSON list endpoint and the CSV export."""
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(ActivityLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if user_id:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(ActivityLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(ActivityLog.created_at <= date_to)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                ActivityLog.entity_label.ilike(term),
                ActivityLog.user_display_name.ilike(term),
            )
        )
    return stmt


@router.get("/recent", response_model=list[ActivityLogResponse])
async def get_recent_activity(
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.organization_id == current_user.organization_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    cutoff = await _retention_cutoff(db, current_user)
    if cutoff is not None:
        rows = [r for r in rows if r.created_at and r.created_at >= cutoff]
    return [ActivityLogResponse.model_validate(r, from_attributes=True) for r in rows]


@router.get("", response_model=list[ActivityLogResponse])
async def list_activity(
    entity_type: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight listing for the entity-detail timeline. Use /report for the admin audit report."""
    stmt = select(ActivityLog)
    stmt = stmt.where(ActivityLog.organization_id == current_user.organization_id)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(ActivityLog.entity_id == entity_id)
    cutoff = await _retention_cutoff(db, current_user)
    if cutoff is not None:
        stmt = stmt.where(ActivityLog.created_at >= cutoff)
    stmt = stmt.order_by(ActivityLog.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    return [ActivityLogResponse.model_validate(r, from_attributes=True) for r in result.scalars().all()]


# ── Audit-log report (admin-only) ────────────────────────────────────────────


@router.get("/report", response_model=PaginatedResponse[ActivityLogResponse])
async def report_activity(
    entity_type: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    date_from: datetime | None = Query(default=None, description="ISO 8601 lower bound (inclusive)"),
    date_to: datetime | None = Query(default=None, description="ISO 8601 upper bound (inclusive)"),
    search: str | None = Query(default=None, description="Substring search on entity label and user name"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Paginated, filterable audit-log report for admins."""
    base = select(ActivityLog)
    base = base.where(ActivityLog.organization_id == current_user.organization_id)
    base = _apply_report_filters(
        base,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    cutoff = await _retention_cutoff(db, current_user)
    if cutoff is not None:
        base = base.where(ActivityLog.created_at >= cutoff)

    count_stmt = select(func.count()).select_from(base.with_only_columns(ActivityLog.id).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    stmt = base.order_by(ActivityLog.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return PaginatedResponse(
        items=[ActivityLogResponse.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/report/export")
async def export_activity_report(
    entity_type: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """CSV export of the filtered audit log. Capped at 50,000 rows."""
    base = select(ActivityLog)
    base = base.where(ActivityLog.organization_id == current_user.organization_id)
    base = _apply_report_filters(
        base,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    cutoff = await _retention_cutoff(db, current_user)
    if cutoff is not None:
        base = base.where(ActivityLog.created_at >= cutoff)
    stmt = base.order_by(ActivityLog.created_at.desc()).limit(50_000)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["When", "User", "Action", "Entity Type", "Entity Label", "Entity ID", "Changes"])
    for r in rows:
        changes_str = ""
        if r.changes:
            try:
                changes_str = "; ".join(
                    f"{k}: {v.get('old')!r} -> {v.get('new')!r}" for k, v in r.changes.items()
                )
            except Exception:
                changes_str = str(r.changes)
        writer.writerow(
            [
                r.created_at.isoformat() if r.created_at else "",
                r.user_display_name,
                r.action,
                r.entity_type,
                r.entity_label,
                str(r.entity_id),
                changes_str,
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=activity_log.csv"},
    )


# ── Filter facets (distinct values for dropdowns) ────────────────────────────


@router.get("/report/facets")
async def report_facets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Distinct values for the audit-log report filters: entity types, actions, users."""
    et = await db.execute(
        select(ActivityLog.entity_type)
        .where(ActivityLog.organization_id == current_user.organization_id)
        .distinct()
        .order_by(ActivityLog.entity_type)
    )
    ac = await db.execute(
        select(ActivityLog.action)
        .where(ActivityLog.organization_id == current_user.organization_id)
        .distinct()
        .order_by(ActivityLog.action)
    )
    us = await db.execute(
        select(ActivityLog.user_id, ActivityLog.user_display_name)
        .where(ActivityLog.organization_id == current_user.organization_id)
        .distinct()
        .order_by(ActivityLog.user_display_name)
    )
    return {
        "entity_types": [r for (r,) in et.all() if r],
        "actions": [r for (r,) in ac.all() if r],
        "users": [
            {"id": str(uid), "name": name}
            for (uid, name) in us.all()
            if uid is not None
        ],
    }


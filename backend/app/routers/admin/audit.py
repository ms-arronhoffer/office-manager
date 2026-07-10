"""Super-admin: cross-org activity log viewer + CSV export."""
import csv
import io
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_console_role
from app.database import get_db
from app.models.activity_log import ActivityLog
from app.models.user import User

router = APIRouter()


class AuditEntry(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    user_id: uuid.UUID
    user_display_name: str
    action: str
    entity_type: str
    entity_id: uuid.UUID
    entity_label: str | None
    changes: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAudit(BaseModel):
    items: list[AuditEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


def _build_audit_stmt(
    org_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    action: str | None,
    entity_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    stmt = select(ActivityLog)
    if org_id:
        stmt = stmt.where(ActivityLog.organization_id == org_id)
    if user_id:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if date_from:
        stmt = stmt.where(ActivityLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(ActivityLog.created_at <= date_to)
    return stmt


@router.get("/export")
async def export_audit(
    org_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support")),
):
    """Export matching audit log entries to CSV (max 10,000 rows)."""
    stmt = _build_audit_stmt(org_id, user_id, action, entity_type, date_from, date_to)
    result = await db.execute(stmt.order_by(ActivityLog.created_at.desc()).limit(10_000))
    entries = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "created_at", "organization_id", "user_display_name",
        "action", "entity_type", "entity_id", "entity_label", "changes",
    ])
    for e in entries:
        writer.writerow([
            e.id, e.created_at, e.organization_id, e.user_display_name,
            e.action, e.entity_type, e.entity_id, e.entity_label,
            e.changes,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@router.get("", response_model=PaginatedAudit)
async def list_audit(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    org_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support")),
):
    stmt = _build_audit_stmt(org_id, user_id, action, entity_type, date_from, date_to)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(ActivityLog.created_at.desc()).offset(offset).limit(page_size))
    entries = result.scalars().all()

    return PaginatedAudit(
        items=[AuditEntry.model_validate(e, from_attributes=True) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)) if total else 1,
    )

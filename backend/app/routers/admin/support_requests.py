"""Super-admin: cross-org support-request queue.

Surfaces support requests submitted from any organization so platform support
staff can see them and drive their status. Org admins already see their own
org's requests via ``/api/v1/support-requests``; this console view spans every
organization and is restricted to the ``super_admin``/``support`` console roles.
"""
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_console_role
from app.database import get_db
from app.models.organization import Organization
from app.models.support_request import SUPPORT_REQUEST_STATUSES, SupportRequest
from app.models.user import User
from app.services.activity_service import log_activity

router = APIRouter()


class SupportRequestRow(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    organization_name: str | None
    subject: str
    message: str
    status: str
    requester_user_id: uuid.UUID | None
    requester_name: str | None
    requester_email: str | None
    created_at: datetime
    updated_at: datetime


class PaginatedSupportRequests(BaseModel):
    items: list[SupportRequestRow]
    total: int
    page: int
    page_size: int
    total_pages: int


class SupportStatusUpdate(BaseModel):
    status: str


@router.get("", response_model=PaginatedSupportRequests)
async def list_support_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    org_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_console_role("super_admin", "support")),
):
    """List support requests across all organizations (newest first)."""
    stmt = select(SupportRequest, Organization.name).outerjoin(
        Organization, Organization.id == SupportRequest.organization_id
    )
    if status_filter:
        stmt = stmt.where(SupportRequest.status == status_filter)
    if org_id:
        stmt = stmt.where(SupportRequest.organization_id == org_id)

    count_stmt = select(func.count()).select_from(SupportRequest)
    if status_filter:
        count_stmt = count_stmt.where(SupportRequest.status == status_filter)
    if org_id:
        count_stmt = count_stmt.where(SupportRequest.organization_id == org_id)
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            stmt.order_by(SupportRequest.created_at.desc()).offset(offset).limit(page_size)
        )
    ).all()

    items = [
        SupportRequestRow(
            id=req.id,
            organization_id=req.organization_id,
            organization_name=org_name,
            subject=req.subject,
            message=req.message,
            status=req.status,
            requester_user_id=req.requester_user_id,
            requester_name=req.requester_name,
            requester_email=req.requester_email,
            created_at=req.created_at,
            updated_at=req.updated_at,
        )
        for req, org_name in rows
    ]
    return PaginatedSupportRequests(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.patch("/{request_id}", response_model=SupportRequestRow)
async def update_support_request_status(
    request_id: uuid.UUID,
    payload: SupportStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_console_role("super_admin", "support")),
):
    """Update the status of any organization's support request."""
    if payload.status not in SUPPORT_REQUEST_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of {SUPPORT_REQUEST_STATUSES}",
        )
    req = (
        await db.execute(select(SupportRequest).where(SupportRequest.id == request_id))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support request not found")

    req.status = payload.status
    await db.commit()
    await db.refresh(req)
    await log_activity(
        db, user=current_user, action="status_changed", entity_type="support_request",
        entity_id=req.id, entity_label=req.subject, changes={"status": payload.status},
    )

    org_name = (
        await db.execute(
            select(Organization.name).where(Organization.id == req.organization_id)
        )
    ).scalar_one_or_none() if req.organization_id else None

    return SupportRequestRow(
        id=req.id,
        organization_id=req.organization_id,
        organization_name=org_name,
        subject=req.subject,
        message=req.message,
        status=req.status,
        requester_user_id=req.requester_user_id,
        requester_name=req.requester_name,
        requester_email=req.requester_email,
        created_at=req.created_at,
        updated_at=req.updated_at,
    )

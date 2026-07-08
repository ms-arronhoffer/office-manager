"""Support Requests API.

A lightweight in-app help channel:

* Any authenticated user can submit a support request (``POST /``). On submit
  the request is stored and best-effort forwarded to the address configured to
  receive support requests (the ``SUPPORT_EMAIL`` environment variable).
* Admins review submissions (``GET /``), update their status
  (``PATCH /{id}``), forward/re-send them to the configured support address
  (``POST /{id}/email``), and delete them (``DELETE /{id}``).
"""
from __future__ import annotations

import html
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.models.support_request import SUPPORT_REQUEST_STATUSES, SupportRequest
from app.models.user import User
from app.utils.email_client import send_email

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────

class SupportRequestCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)


class SupportRequestStatusUpdate(BaseModel):
    status: str


class SupportRequestResponse(BaseModel):
    id: uuid.UUID
    subject: str
    message: str
    status: str
    requester_user_id: uuid.UUID | None
    requester_name: str | None
    requester_email: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SupportEmailResult(BaseModel):
    sent: bool
    support_email: str | None
    detail: str


class SupportConfigResponse(BaseModel):
    support_email: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _support_email() -> str | None:
    """Return the configured support recipient address, if any.

    Configured via the ``SUPPORT_EMAIL`` environment variable (not admin UI),
    so it applies platform-wide and can't be changed without deploy access.
    """
    value = settings.SUPPORT_EMAIL
    return (value or "").strip() or None


def _format_body(req: SupportRequest) -> str:
    # The email is sent as HTML, so all user-provided values are HTML-escaped to
    # avoid injecting markup. Angle brackets around the email are emitted as
    # entities so they render literally as ``Name <email>``.
    name = html.escape(req.requester_name or "Unknown")
    requester = name
    if req.requester_email:
        requester = f"{name} &lt;{html.escape(req.requester_email)}&gt;"
    subject = html.escape(req.subject)
    # Preserve line breaks from the free-text message.
    message = html.escape(req.message).replace("\n", "<br/>")
    return (
        f"<p>A new support request was submitted in the application.</p>"
        f"<p><strong>From:</strong> {requester}<br/>"
        f"<strong>Subject:</strong> {subject}</p>"
        f"<hr/><p>{message}</p>"
    )


async def _forward(req: SupportRequest) -> tuple[bool, str | None]:
    """Best-effort forward a support request to the configured support address."""
    support_email = _support_email()
    if not support_email:
        return False, None
    try:
        sent = await send_email(
            to=support_email,
            subject=f"[Support Request] {req.subject}",
            html_body=_format_body(req),
        )
    except Exception:  # pragma: no cover - defensive; email is best-effort
        logger.exception("Failed to forward support request %s", req.id)
        sent = False
    return sent, support_email


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=SupportRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_support_request(
    payload: SupportRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = SupportRequest(
        organization_id=current_user.organization_id,
        subject=payload.subject.strip(),
        message=payload.message.strip(),
        status="open",
        requester_user_id=current_user.id,
        requester_name=current_user.display_name,
        requester_email=current_user.email,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # Best-effort forward to the configured support address; never blocks submit.
    await _forward(req)

    return SupportRequestResponse.model_validate(req)


@router.get("/config", response_model=SupportConfigResponse)
async def get_support_config(
    current_user: User = Depends(require_role("admin")),
):
    """Expose the platform-wide support recipient (set via SUPPORT_EMAIL env var)."""
    return SupportConfigResponse(support_email=_support_email())


@router.get("", response_model=list[SupportRequestResponse])
async def list_support_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    stmt = select(SupportRequest).where(
        SupportRequest.organization_id == current_user.organization_id
    )
    if status_filter:
        stmt = stmt.where(SupportRequest.status == status_filter)
    stmt = stmt.order_by(SupportRequest.created_at.desc())
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [SupportRequestResponse.model_validate(r) for r in rows]


async def _get_owned(
    request_id: uuid.UUID, db: AsyncSession, current_user: User
) -> SupportRequest:
    res = await db.execute(
        select(SupportRequest).where(
            SupportRequest.id == request_id,
            SupportRequest.organization_id == current_user.organization_id,
        )
    )
    req = res.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support request not found")
    return req


@router.patch("/{request_id}", response_model=SupportRequestResponse)
async def update_support_request(
    request_id: uuid.UUID,
    payload: SupportRequestStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.status not in SUPPORT_REQUEST_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of {SUPPORT_REQUEST_STATUSES}",
        )
    req = await _get_owned(request_id, db, current_user)
    req.status = payload.status
    await db.commit()
    await db.refresh(req)
    return SupportRequestResponse.model_validate(req)


@router.post("/{request_id}/email", response_model=SupportEmailResult)
async def email_support_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    req = await _get_owned(request_id, db, current_user)
    sent, support_email = await _forward(req)
    if support_email is None:
        return SupportEmailResult(
            sent=False,
            support_email=None,
            detail="No support email is configured. Set SUPPORT_EMAIL in the environment.",
        )
    detail = (
        f"Support request forwarded to {support_email}."
        if sent
        else "Email could not be sent. Check the SMTP configuration."
    )
    return SupportEmailResult(sent=sent, support_email=support_email, detail=detail)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_support_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    req = await _get_owned(request_id, db, current_user)
    await db.delete(req)
    await db.commit()

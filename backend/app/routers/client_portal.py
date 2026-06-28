"""Client self-service portal.

Token-gated endpoints that let an external landlord or management company:

* view their (read-only) profile,
* manage their *secondary* contacts (the shared ``entity_contacts``), and
* upload documents.

Access is bootstrapped by an internal admin/editor who generates a single-use
*signup* link. Redeeming it activates a persistent *portal* token that the
external party keeps using thereafter.
"""
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.attachment import Attachment
from app.models.client_portal_account import (
    ClientPortalAccount,
    CLIENT_PORTAL_ENTITY_TYPES,
)
from app.models.client_portal_change_request import (
    ClientPortalChangeRequest,
    CHANGE_REQUEST_STATUSES,
)
from app.models.entity_contact import EntityContact
from app.models.landlord import Landlord
from app.models.management_company import ManagementCompany
from app.models.organization import Organization
from app.models.user import User
from app.schemas.attachment import AttachmentResponse
from app.schemas.entity_contact import (
    EntityContactCreate,
    EntityContactResponse,
    EntityContactUpdate,
)
from app.services import entitlements as ent
from app.services.activity_service import log_activity
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

router = APIRouter()

# Signup invites are short-lived; the portal credential is long-lived.
_SIGNUP_TTL_DAYS = 7
_PORTAL_TTL_DAYS = 365

# Entitlement feature key gating the client portal (Pro plan and above).
_PORTAL_FEATURE = "client_portal"

# Marker stamped on attachments uploaded through the portal; only these may be
# deleted by the portal user (internal documents are off-limits).
_PORTAL_UPLOADER = "client_portal"

# Profile fields a client may propose changes to. Both supported entity types
# expose these columns, so a single whitelist covers both.
_EDITABLE_PROFILE_FIELDS = (
    "contact_name",
    "contact_email",
    "contact_phone",
    "website",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "zip_code",
)

_ENTITY_MODELS = {
    "landlord": Landlord,
    "management_company": ManagementCompany,
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[\r\n\t\x00-\x1f\x7f]")


# ── Schemas ──────────────────────────────────────────────────────────────────

class PortalInviteRequest(BaseModel):
    entity_type: str
    entity_id: uuid.UUID


class PortalInviteResponse(BaseModel):
    signup_token: str
    signup_url: str
    expires_at: datetime
    activated: bool


class PortalSignupRequest(BaseModel):
    token: str


class PortalSessionResponse(BaseModel):
    portal_token: str
    portal_url: str
    expires_at: datetime
    entity_type: str


class PortalProfileResponse(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None


class ChangeRequestCreate(BaseModel):
    # Proposed new values for whitelisted profile fields. Unknown keys are
    # rejected; empty payloads are rejected.
    proposed_changes: dict[str, Optional[str]]
    message: Optional[str] = None


class ChangeRequestResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    status: str
    proposed_changes: dict
    message: Optional[str] = None
    reviewed_by_display_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangeRequestReview(BaseModel):
    review_note: Optional[str] = None


class PortalStatusResponse(BaseModel):
    exists: bool
    status: str  # none | invited | active | revoked | expired
    activated_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    portal_token_expires_at: Optional[datetime] = None
    pending_change_requests: int = 0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _load_entity(db: AsyncSession, entity_type: str, entity_id: uuid.UUID, org_id):
    Model = _ENTITY_MODELS[entity_type]
    result = await db.execute(
        select(Model).where(
            Model.id == entity_id,
            Model.organization_id == org_id,
            Model.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def _assert_org_entitled(db: AsyncSession, org_id) -> None:
    """Ensure the owning organization is entitled to the client portal.

    Org-less accounts (internal/platform data, e.g. seed/test orgs) bypass the
    gate, mirroring ``require_feature`` semantics. Orgs that lack the feature
    (e.g. after a downgrade) lose portal access with a 403.
    """
    if org_id is None:
        return
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org is None or not ent.has_feature(org, _PORTAL_FEATURE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The client portal is not available on your organization's current plan.",
        )


async def _notify_staff(
    db: AsyncSession,
    *,
    org_id,
    kind: str,
    title: str,
    body: str | None,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    """Best-effort: notify active admin/editor staff of a portal event."""
    try:
        result = await db.execute(
            select(User).where(
                User.organization_id == org_id,
                User.role.in_(("admin", "editor")),
                User.is_active.is_(True),
            )
        )
        recipients = result.scalars().all()
        for user in recipients:
            await create_notification(
                db,
                user_id=user.id,
                kind=kind,
                title=title,
                body=body,
                entity_type=entity_type,
                entity_id=entity_id,
            )
    except Exception:  # noqa: BLE001 - notifications must never block the action
        await db.rollback()
        logger.exception("Failed to notify staff of portal event %s", kind)


def _entity_profile(entity_type: str, entity) -> PortalProfileResponse:
    """Build a read-only profile view for either supported entity type."""
    parts = [
        getattr(entity, "address_line_1", None),
        getattr(entity, "address_line_2", None),
        getattr(entity, "city", None),
        getattr(entity, "state", None),
        getattr(entity, "zip_code", None),
    ]
    address = ", ".join(p for p in parts if p) or getattr(entity, "address", None)

    if entity_type == "landlord":
        name = entity.landlord_company or entity.contact_name
    else:  # management_company
        name = entity.name

    return PortalProfileResponse(
        entity_type=entity_type,
        entity_id=entity.id,
        name=name,
        contact_name=getattr(entity, "contact_name", None),
        contact_email=getattr(entity, "contact_email", None),
        contact_phone=getattr(entity, "contact_phone", None),
        address=address,
        website=getattr(entity, "website", None),
    )


# ── Auth dependency (portal token) ───────────────────────────────────────────

async def get_portal_account(
    x_portal_token: str = Header(None, alias="X-Portal-Token"),
    db: AsyncSession = Depends(get_db),
) -> ClientPortalAccount:
    if not x_portal_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Portal token required")
    result = await db.execute(
        select(ClientPortalAccount).where(ClientPortalAccount.portal_token == x_portal_token)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid portal token")
    if account.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Portal access has been revoked")
    expires = _aware(account.portal_token_expires_at)
    if expires and expires < _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Portal token expired")
    # Gate by the owning organization's plan entitlement.
    await _assert_org_entitled(db, account.organization_id)
    # Sliding-window activity tracking (best-effort; never blocks the request).
    try:
        account.last_active_at = _now()
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
    return account


# ── Internal: generate single-use signup invite (JWT admin/editor) ───────────

@router.post("/client-portal/invite", response_model=PortalInviteResponse)
async def generate_invite(
    payload: PortalInviteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create (or refresh) a one-time signup link for a landlord or management company."""
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    await _assert_org_entitled(db, current_user.organization_id)
    if payload.entity_type not in CLIENT_PORTAL_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported entity_type '{payload.entity_type}'. Allowed: {', '.join(CLIENT_PORTAL_ENTITY_TYPES)}",
        )

    entity = await _load_entity(db, payload.entity_type, payload.entity_id, current_user.organization_id)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    result = await db.execute(
        select(ClientPortalAccount).where(
            ClientPortalAccount.entity_type == payload.entity_type,
            ClientPortalAccount.entity_id == entity.id,
            ClientPortalAccount.organization_id == current_user.organization_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = ClientPortalAccount(
            organization_id=current_user.organization_id,
            entity_type=payload.entity_type,
            entity_id=entity.id,
        )
        db.add(account)

    token = secrets.token_hex(32)
    expires_at = _now() + timedelta(days=_SIGNUP_TTL_DAYS)
    account.signup_token = token
    account.signup_token_expires_at = expires_at
    # A fresh invite re-opens onboarding and clears any prior revocation.
    account.activated_at = None
    account.revoked_at = None

    await db.commit()

    return PortalInviteResponse(
        signup_token=token,
        signup_url=f"/client-portal/signup?token={token}",
        expires_at=expires_at,
        activated=False,
    )


# ── Public: redeem signup invite (one-time) ──────────────────────────────────

@router.post("/client-portal/signup", response_model=PortalSessionResponse)
async def redeem_signup(
    payload: PortalSignupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Redeem a single-use signup token and mint a persistent portal token."""
    result = await db.execute(
        select(ClientPortalAccount).where(ClientPortalAccount.signup_token == payload.token)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or already-used signup link")

    expires = _aware(account.signup_token_expires_at)
    if expires and expires < _now():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This signup link has expired")

    # Block activation if the owning org is no longer entitled to the portal.
    await _assert_org_entitled(db, account.organization_id)

    portal_token = secrets.token_hex(32)
    portal_expires = _now() + timedelta(days=_PORTAL_TTL_DAYS)
    account.portal_token = portal_token
    account.portal_token_expires_at = portal_expires
    account.activated_at = _now()
    account.revoked_at = None
    # Consume the single-use signup token.
    account.signup_token = None
    account.signup_token_expires_at = None

    await db.commit()

    return PortalSessionResponse(
        portal_token=portal_token,
        portal_url=f"/client-portal?token={portal_token}",
        expires_at=portal_expires,
        entity_type=account.entity_type,
    )


# ── Portal: profile (read-only) ──────────────────────────────────────────────

@router.get("/client-portal/me", response_model=PortalProfileResponse)
async def portal_profile(
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    entity = await _load_entity(db, account.entity_type, account.entity_id, account.organization_id)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return _entity_profile(account.entity_type, entity)


# ── Portal: secondary contacts (editable) ────────────────────────────────────

@router.get("/client-portal/contacts", response_model=list[EntityContactResponse])
async def portal_list_contacts(
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EntityContact)
        .where(
            EntityContact.entity_type == account.entity_type,
            EntityContact.entity_id == account.entity_id,
            EntityContact.organization_id == account.organization_id,
        )
        .order_by(EntityContact.is_primary.desc(), EntityContact.contact_name)
    )
    return [EntityContactResponse.model_validate(c, from_attributes=True) for c in result.scalars().all()]


@router.post("/client-portal/contacts", response_model=EntityContactResponse, status_code=status.HTTP_201_CREATED)
async def portal_create_contact(
    payload: EntityContactCreate,
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump()
    # Force entity scoping from the authenticated portal account; never trust the body.
    data["entity_type"] = account.entity_type
    data["entity_id"] = account.entity_id
    contact = EntityContact(**data, organization_id=account.organization_id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return EntityContactResponse.model_validate(contact, from_attributes=True)


async def _load_portal_contact(
    db: AsyncSession, contact_id: uuid.UUID, account: ClientPortalAccount
) -> EntityContact:
    result = await db.execute(
        select(EntityContact).where(
            EntityContact.id == contact_id,
            EntityContact.entity_type == account.entity_type,
            EntityContact.entity_id == account.entity_id,
            EntityContact.organization_id == account.organization_id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.put("/client-portal/contacts/{contact_id}", response_model=EntityContactResponse)
async def portal_update_contact(
    contact_id: uuid.UUID,
    payload: EntityContactUpdate,
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    contact = await _load_portal_contact(db, contact_id, account)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    await db.commit()
    await db.refresh(contact)
    return EntityContactResponse.model_validate(contact, from_attributes=True)


@router.delete("/client-portal/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def portal_delete_contact(
    contact_id: uuid.UUID,
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    contact = await _load_portal_contact(db, contact_id, account)
    await db.delete(contact)
    await db.commit()


# ── Portal: documents ────────────────────────────────────────────────────────

def _allowed_extensions() -> set[str]:
    return {ext.strip().lower() for ext in settings.ALLOWED_EXTENSIONS.split(",")}


@router.get("/client-portal/documents", response_model=list[AttachmentResponse])
async def portal_list_documents(
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Attachment)
        .where(
            Attachment.entity_type == account.entity_type,
            Attachment.entity_id == account.entity_id,
        )
        .order_by(Attachment.created_at.desc())
    )
    return [AttachmentResponse.model_validate(a, from_attributes=True) for a in result.scalars().all()]


@router.post(
    "/client-portal/documents",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def portal_upload_document(
    file: UploadFile = File(...),
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")

    # Path(...).name already strips directory components; reject anything that
    # still looks like a traversal attempt or is empty after sanitization.
    safe_name = _UNSAFE_FILENAME_CHARS.sub("", Path(file.filename).name)
    if not safe_name or safe_name in (".", "..") or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    ext = Path(safe_name).suffix.lower()
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

    upload_dir = Path(settings.UPLOAD_DIR) / account.entity_type
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{ext}"
    (upload_dir / stored_name).write_bytes(content)

    attachment = Attachment(
        organization_id=account.organization_id,
        entity_type=account.entity_type,
        entity_id=account.entity_id,
        original_filename=safe_name,
        stored_filename=stored_name,
        content_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        uploaded_by=_PORTAL_UPLOADER,
        description="client-upload",
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    # Build the response BEFORE best-effort notifications so a notification
    # failure can't poison the session and 500 the upload.
    response = AttachmentResponse.model_validate(attachment, from_attributes=True)
    await _notify_staff(
        db,
        org_id=account.organization_id,
        kind="client_portal_document",
        title="Client uploaded a document",
        body=f"A {account.entity_type.replace('_', ' ')} uploaded '{safe_name}' via the client portal.",
        entity_type=account.entity_type,
        entity_id=account.entity_id,
    )
    return response


def _sanitize_download_name(name: str) -> str:
    name = _UNSAFE_FILENAME_CHARS.sub("", Path(name).name).strip()
    return name or "download"


async def _load_portal_document(
    db: AsyncSession, attachment_id: uuid.UUID, account: ClientPortalAccount
) -> Attachment:
    result = await db.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.entity_type == account.entity_type,
            Attachment.entity_id == account.entity_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return attachment


@router.get("/client-portal/documents/{attachment_id}/download")
async def portal_download_document(
    attachment_id: uuid.UUID,
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    attachment = await _load_portal_document(db, attachment_id, account)
    file_path = Path(settings.UPLOAD_DIR) / attachment.entity_type / attachment.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return FileResponse(
        path=str(file_path),
        filename=_sanitize_download_name(attachment.original_filename),
        media_type=attachment.content_type,
    )


@router.delete("/client-portal/documents/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def portal_delete_document(
    attachment_id: uuid.UUID,
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    attachment = await _load_portal_document(db, attachment_id, account)
    # Clients may only delete documents they uploaded — never internal files.
    if attachment.uploaded_by != _PORTAL_UPLOADER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only remove documents you uploaded through the portal.",
        )
    file_path = Path(settings.UPLOAD_DIR) / attachment.entity_type / attachment.stored_filename
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass
    await db.delete(attachment)
    await db.commit()


# ── Portal: profile change requests ──────────────────────────────────────────

def _validate_proposed_changes(proposed: dict[str, Optional[str]]) -> dict[str, Optional[str]]:
    """Whitelist + normalize a proposed-changes payload."""
    cleaned: dict[str, Optional[str]] = {}
    for key, value in proposed.items():
        if key not in _EDITABLE_PROFILE_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{key}' cannot be changed via the portal.",
            )
        if value is not None:
            value = str(value).strip() or None
        cleaned[key] = value
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No changes were provided.",
        )
    return cleaned


@router.get("/client-portal/change-requests", response_model=list[ChangeRequestResponse])
async def portal_list_change_requests(
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientPortalChangeRequest)
        .where(ClientPortalChangeRequest.account_id == account.id)
        .order_by(ClientPortalChangeRequest.created_at.desc())
    )
    return [
        ChangeRequestResponse.model_validate(r, from_attributes=True)
        for r in result.scalars().all()
    ]


@router.post(
    "/client-portal/change-requests",
    response_model=ChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def portal_create_change_request(
    payload: ChangeRequestCreate,
    account: ClientPortalAccount = Depends(get_portal_account),
    db: AsyncSession = Depends(get_db),
):
    cleaned = _validate_proposed_changes(payload.proposed_changes)
    cr = ClientPortalChangeRequest(
        organization_id=account.organization_id,
        account_id=account.id,
        entity_type=account.entity_type,
        entity_id=account.entity_id,
        status="pending",
        proposed_changes=cleaned,
        message=(payload.message or "").strip() or None,
    )
    db.add(cr)
    await db.commit()
    await db.refresh(cr)

    response = ChangeRequestResponse.model_validate(cr, from_attributes=True)
    await _notify_staff(
        db,
        org_id=account.organization_id,
        kind="client_portal_change_request",
        title="Client submitted a profile change request",
        body=f"A {account.entity_type.replace('_', ' ')} requested updates to {len(cleaned)} field(s) via the client portal.",
        entity_type=account.entity_type,
        entity_id=account.entity_id,
    )
    return response



# ── Internal (JWT admin/editor): portal lifecycle & change-request review ─────

class PortalRevokeRotateRequest(BaseModel):
    entity_type: str
    entity_id: uuid.UUID


def _require_internal_editor(current_user: User) -> None:
    if current_user.role not in ("admin", "editor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


async def _load_account_for_entity(
    db: AsyncSession, entity_type: str, entity_id: uuid.UUID, org_id
) -> ClientPortalAccount | None:
    result = await db.execute(
        select(ClientPortalAccount).where(
            ClientPortalAccount.entity_type == entity_type,
            ClientPortalAccount.entity_id == entity_id,
            ClientPortalAccount.organization_id == org_id,
        )
    )
    return result.scalar_one_or_none()


def _account_status(account: ClientPortalAccount) -> str:
    if account.revoked_at is not None:
        return "revoked"
    if account.activated_at is None:
        return "invited"
    expires = _aware(account.portal_token_expires_at)
    if expires and expires < _now():
        return "expired"
    return "active"


async def _count_pending_change_requests(db: AsyncSession, account_id: uuid.UUID) -> int:
    result = await db.execute(
        select(ClientPortalChangeRequest.id).where(
            ClientPortalChangeRequest.account_id == account_id,
            ClientPortalChangeRequest.status == "pending",
        )
    )
    return len(result.scalars().all())


@router.get("/client-portal/admin/status", response_model=PortalStatusResponse)
async def admin_portal_status(
    entity_type: str,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return portal access status + pending change-request count for an entity."""
    _require_internal_editor(current_user)
    if entity_type not in CLIENT_PORTAL_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity_type")

    account = await _load_account_for_entity(db, entity_type, entity_id, current_user.organization_id)
    if account is None:
        return PortalStatusResponse(exists=False, status="none")

    pending = await _count_pending_change_requests(db, account.id)
    return PortalStatusResponse(
        exists=True,
        status=_account_status(account),
        activated_at=account.activated_at,
        last_active_at=account.last_active_at,
        revoked_at=account.revoked_at,
        portal_token_expires_at=account.portal_token_expires_at,
        pending_change_requests=pending,
    )


@router.post("/client-portal/admin/revoke", response_model=PortalStatusResponse)
async def admin_revoke_portal(
    payload: PortalRevokeRotateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Immediately revoke an entity's portal access."""
    _require_internal_editor(current_user)
    if payload.entity_type not in CLIENT_PORTAL_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity_type")

    account = await _load_account_for_entity(db, payload.entity_type, payload.entity_id, current_user.organization_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portal account not found")

    account.revoked_at = _now()
    # Invalidate the credential so it can never be reused.
    account.portal_token = None
    account.portal_token_expires_at = None
    await db.commit()
    await db.refresh(account)

    status_resp = PortalStatusResponse(
        exists=True,
        status=_account_status(account),
        activated_at=account.activated_at,
        last_active_at=account.last_active_at,
        revoked_at=account.revoked_at,
        portal_token_expires_at=account.portal_token_expires_at,
        pending_change_requests=await _count_pending_change_requests(db, account.id),
    )
    await log_activity(
        db,
        user=current_user,
        action="client_portal.revoke",
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        entity_label="Client portal access",
    )
    return status_resp


@router.post("/client-portal/admin/rotate", response_model=PortalSessionResponse)
async def admin_rotate_portal(
    payload: PortalRevokeRotateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rotate (re-issue) an active portal credential, invalidating the old one."""
    _require_internal_editor(current_user)
    await _assert_org_entitled(db, current_user.organization_id)
    if payload.entity_type not in CLIENT_PORTAL_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity_type")

    account = await _load_account_for_entity(db, payload.entity_type, payload.entity_id, current_user.organization_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portal account not found")
    if account.activated_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Portal has not been activated yet; send the signup invite instead.",
        )

    portal_token = secrets.token_hex(32)
    portal_expires = _now() + timedelta(days=_PORTAL_TTL_DAYS)
    account.portal_token = portal_token
    account.portal_token_expires_at = portal_expires
    account.revoked_at = None
    await db.commit()

    await log_activity(
        db,
        user=current_user,
        action="client_portal.rotate",
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        entity_label="Client portal access",
    )
    return PortalSessionResponse(
        portal_token=portal_token,
        portal_url=f"/client-portal?token={portal_token}",
        expires_at=portal_expires,
        entity_type=account.entity_type,
    )


@router.get("/client-portal/admin/change-requests", response_model=list[ChangeRequestResponse])
async def admin_list_change_requests(
    entity_type: str,
    entity_id: uuid.UUID,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List change requests for an entity (optionally filtered by status)."""
    _require_internal_editor(current_user)
    if entity_type not in CLIENT_PORTAL_ENTITY_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity_type")

    stmt = select(ClientPortalChangeRequest).where(
        ClientPortalChangeRequest.entity_type == entity_type,
        ClientPortalChangeRequest.entity_id == entity_id,
        ClientPortalChangeRequest.organization_id == current_user.organization_id,
    )
    if status_filter:
        if status_filter not in CHANGE_REQUEST_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status")
        stmt = stmt.where(ClientPortalChangeRequest.status == status_filter)
    stmt = stmt.order_by(ClientPortalChangeRequest.created_at.desc())
    result = await db.execute(stmt)
    return [
        ChangeRequestResponse.model_validate(r, from_attributes=True)
        for r in result.scalars().all()
    ]


async def _load_admin_change_request(
    db: AsyncSession, request_id: uuid.UUID, current_user: User
) -> ClientPortalChangeRequest:
    result = await db.execute(
        select(ClientPortalChangeRequest).where(
            ClientPortalChangeRequest.id == request_id,
            ClientPortalChangeRequest.organization_id == current_user.organization_id,
        )
    )
    cr = result.scalar_one_or_none()
    if not cr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change request not found")
    return cr


@router.post(
    "/client-portal/admin/change-requests/{request_id}/approve",
    response_model=ChangeRequestResponse,
)
async def admin_approve_change_request(
    request_id: uuid.UUID,
    payload: ChangeRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a change request, applying the proposed values to the entity."""
    _require_internal_editor(current_user)
    cr = await _load_admin_change_request(db, request_id, current_user)
    if cr.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Change request already reviewed")

    entity = await _load_entity(db, cr.entity_type, cr.entity_id, current_user.organization_id)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    # Apply only whitelisted fields that actually exist on the model.
    applied: dict = {}
    for field, value in (cr.proposed_changes or {}).items():
        if field in _EDITABLE_PROFILE_FIELDS and hasattr(entity, field):
            applied[field] = {"old": getattr(entity, field), "new": value}
            setattr(entity, field, value)

    cr.status = "approved"
    cr.reviewed_by_user_id = current_user.id
    cr.reviewed_by_display_name = current_user.display_name or current_user.email
    cr.reviewed_at = _now()
    cr.review_note = (payload.review_note or "").strip() or None
    await db.commit()
    await db.refresh(cr)

    response = ChangeRequestResponse.model_validate(cr, from_attributes=True)
    await log_activity(
        db,
        user=current_user,
        action="client_portal.change_request.approve",
        entity_type=cr.entity_type,
        entity_id=cr.entity_id,
        entity_label="Client portal change request",
        changes=applied or None,
    )
    return response


@router.post(
    "/client-portal/admin/change-requests/{request_id}/reject",
    response_model=ChangeRequestResponse,
)
async def admin_reject_change_request(
    request_id: uuid.UUID,
    payload: ChangeRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a change request without applying any changes."""
    _require_internal_editor(current_user)
    cr = await _load_admin_change_request(db, request_id, current_user)
    if cr.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Change request already reviewed")

    cr.status = "rejected"
    cr.reviewed_by_user_id = current_user.id
    cr.reviewed_by_display_name = current_user.display_name or current_user.email
    cr.reviewed_at = _now()
    cr.review_note = (payload.review_note or "").strip() or None
    await db.commit()
    await db.refresh(cr)

    response = ChangeRequestResponse.model_validate(cr, from_attributes=True)
    await log_activity(
        db,
        user=current_user,
        action="client_portal.change_request.reject",
        entity_type=cr.entity_type,
        entity_id=cr.entity_id,
        entity_label="Client portal change request",
    )
    return response

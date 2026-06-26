"""Client self-service portal.

Token-gated endpoints that let an external landlord or management company:

* view their (read-only) profile,
* manage their *secondary* contacts (the shared ``entity_contacts``), and
* upload documents.

Access is bootstrapped by an internal admin/editor who generates a single-use
*signup* link. Redeeming it activates a persistent *portal* token that the
external party keeps using thereafter.
"""
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
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
from app.models.entity_contact import EntityContact
from app.models.landlord import Landlord
from app.models.management_company import ManagementCompany
from app.models.user import User
from app.schemas.attachment import AttachmentResponse
from app.schemas.entity_contact import (
    EntityContactCreate,
    EntityContactResponse,
    EntityContactUpdate,
)

router = APIRouter()

# Signup invites are short-lived; the portal credential is long-lived.
_SIGNUP_TTL_DAYS = 7
_PORTAL_TTL_DAYS = 365

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
    expires = _aware(account.portal_token_expires_at)
    if expires and expires < _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Portal token expired")
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
    # A fresh invite re-opens onboarding.
    account.activated_at = None

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

    portal_token = secrets.token_hex(32)
    portal_expires = _now() + timedelta(days=_PORTAL_TTL_DAYS)
    account.portal_token = portal_token
    account.portal_token_expires_at = portal_expires
    account.activated_at = _now()
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
        uploaded_by="client_portal",
        description="client-upload",
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return AttachmentResponse.model_validate(attachment, from_attributes=True)

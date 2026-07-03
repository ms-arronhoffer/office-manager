import re
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.models.attachment import Attachment
from app.models.hvac_contract import HvacContract
from app.models.landlord import Landlord
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.management_company import ManagementCompany
from app.models.office import Office
from app.models.transition import OfficeTransition
from app.models.user import User
from app.models.vendor import Vendor
from app.models.inspection import Inspection
from app.schemas.attachment import AttachmentResponse
from app.services import document_search_service

router = APIRouter()

logger = logging.getLogger(__name__)

# Map entity_type string -> SQLAlchemy model class.
# Models all use SoftDeleteMixin (is_deleted column).
ENTITY_MODELS = {
    "lease": Lease,
    "hvac_contract": HvacContract,
    "office": Office,
    "landlord": Landlord,
    "transition": OfficeTransition,
    "maintenance_ticket": MaintenanceTicket,
    "vendor": Vendor,
    "management_company": ManagementCompany,
    "inspection": Inspection,
}
ALLOWED_ENTITY_TYPES = set(ENTITY_MODELS.keys())

# Regex of characters that are unsafe in HTTP header values (CRLF, NUL, control chars).
_UNSAFE_FILENAME_CHARS = re.compile(r"[\r\n\t\x00-\x1f\x7f]")


def _allowed_extensions() -> set[str]:
    return {ext.strip().lower() for ext in settings.ALLOWED_EXTENSIONS.split(",")}


def _upload_dir(entity_type: str) -> Path:
    p = Path(settings.UPLOAD_DIR) / entity_type
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sanitize_filename(name: str) -> str:
    """
    Strip path components and control characters from a user-supplied filename
    before echoing it back in a Content-Disposition header. Defends against
    response-header injection (CRLF) and path traversal.
    """
    # Strip any path components a malicious client may have included.
    name = Path(name).name
    # Remove characters that are invalid in HTTP header values.
    name = _UNSAFE_FILENAME_CHARS.sub("", name)
    # Fall back to a generic name if the result is empty.
    return name.strip() or "download"


async def _ensure_parent_exists(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> None:
    """
    Verify the parent entity exists and is not soft-deleted.
    Prevents creating orphan attachments and blocks attempts to read/write
    files for entities the user shouldn't be able to see.
    """
    Model = ENTITY_MODELS[entity_type]
    stmt = select(Model.id).where(Model.id == entity_id)
    # All entity models in this app use SoftDeleteMixin.
    if hasattr(Model, "is_deleted"):
        stmt = stmt.where(Model.is_deleted.is_(False))
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parent {entity_type} not found.",
        )


# ── List attachments ──────────────────────────────────────────────────────────

@router.get(
    "/{entity_type}/{entity_id}/attachments",
    response_model=list[AttachmentResponse],
)
async def list_attachments(
    entity_type: str,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    await _ensure_parent_exists(db, entity_type, entity_id)

    result = await db.execute(
        select(Attachment)
        .where(Attachment.entity_type == entity_type, Attachment.entity_id == entity_id)
        .order_by(Attachment.created_at.desc())
    )
    return [AttachmentResponse.model_validate(a, from_attributes=True) for a in result.scalars().all()]


# ── Upload attachment ─────────────────────────────────────────────────────────

@router.post(
    "/{entity_type}/{entity_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    entity_type: str,
    entity_id: uuid.UUID,
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    await _ensure_parent_exists(db, entity_type, entity_id)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    safe_filename = _sanitize_filename(file.filename)
    ext = Path(safe_filename).suffix.lower()
    if ext not in _allowed_extensions():
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not allowed. Allowed: {settings.ALLOWED_EXTENSIONS}",
        )

    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB} MB.",
        )

    stored_name = f"{uuid.uuid4()}{ext}"
    dest = _upload_dir(entity_type) / stored_name
    dest.write_bytes(content)

    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        original_filename=safe_filename,
        stored_filename=stored_name,
        content_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        uploaded_by=current_user.email,
        description=description,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    # Best-effort: index attachment text for keyword/semantic search across all
    # entity types, strictly scoped to the parent's organization.
    try:
        Model = ENTITY_MODELS[entity_type]
        parent = (
            await db.execute(select(Model).where(Model.id == entity_id))
        ).scalar_one_or_none()
        parent_org = getattr(parent, "organization_id", None) if parent else None
        if attachment.organization_id is None and parent_org is not None:
            attachment.organization_id = parent_org
            await db.commit()
            await db.refresh(attachment)
        org_id = attachment.organization_id or parent_org
        lease = parent if entity_type == "lease" else None
        await document_search_service.index_document(
            db,
            attachment=attachment,
            content=content,
            organization_id=org_id,
            entity_type=entity_type,
            entity_id=entity_id,
            lease=lease,
        )
    except Exception:  # noqa: BLE001 - indexing must never block upload
        await db.rollback()
        logger.exception("Failed to index attachment %s", attachment.id)

    return AttachmentResponse.model_validate(attachment, from_attributes=True)


# ── Download attachment ───────────────────────────────────────────────────────

@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # If the parent entity has been soft-deleted, deny download.
    if attachment.entity_type in ENTITY_MODELS:
        await _ensure_parent_exists(db, attachment.entity_type, attachment.entity_id)

    file_path = Path(settings.UPLOAD_DIR) / attachment.entity_type / attachment.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=_sanitize_filename(attachment.original_filename),
        media_type=attachment.content_type,
    )


# ── Delete attachment ─────────────────────────────────────────────────────────

@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = Path(settings.UPLOAD_DIR) / attachment.entity_type / attachment.stored_filename
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass

    await db.delete(attachment)
    await db.commit()


# ── Upload limits (used by the frontend for client-side validation) ───────────


@router.get("/attachments/limits")
async def get_upload_limits(_: User = Depends(get_current_user)):
    return {
        "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        "max_file_size_bytes": settings.MAX_FILE_SIZE_MB * 1024 * 1024,
        "allowed_extensions": sorted(_allowed_extensions()),
        "allowed_entity_types": sorted(ALLOWED_ENTITY_TYPES),
    }


# ── Batch attachment counts (for "Has Attachments" columns on list pages) ─────


@router.get("/attachments/counts")
async def get_attachment_counts(
    entity_type: str = Query(..., description="Entity type, e.g. 'lease'"),
    ids: str = Query(..., description="Comma-separated UUIDs of parent entities"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    raw_ids = [s.strip() for s in ids.split(",") if s.strip()]
    if not raw_ids:
        return {}
    if len(raw_ids) > 500:
        raise HTTPException(status_code=400, detail="Too many ids requested (max 500).")

    parsed_ids: list[uuid.UUID] = []
    for s in raw_ids:
        try:
            parsed_ids.append(uuid.UUID(s))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid UUID: {s}")

    stmt = (
        select(Attachment.entity_id, func.count(Attachment.id))
        .where(
            Attachment.entity_type == entity_type,
            Attachment.entity_id.in_(parsed_ids),
        )
        .group_by(Attachment.entity_id)
    )
    result = await db.execute(stmt)
    counts: dict[str, int] = {str(eid): 0 for eid in parsed_ids}
    for entity_id, count in result.all():
        counts[str(entity_id)] = int(count)
    return counts

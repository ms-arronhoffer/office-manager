"""Keyword / semantic search over documents attached to leases.

Mounted under ``/api/v1/leases`` alongside the main leases router. Endpoints:

* ``POST /{lease_id}/document-search`` — search within a single lease's documents.
* ``POST /document-search`` — portfolio-wide search across the org's leases.
* ``POST /{lease_id}/reindex-documents`` — (re)build the index for a lease's
  existing attachments (backfill).

Search degrades gracefully: semantic ranking is used when Gemini is configured
and embedded chunks exist, otherwise a keyword scan is used.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.lease import Lease
from app.models.user import User
from app.services import document_search_service
from app.services import usage_service

router = APIRouter()


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    attachment_id: uuid.UUID | None = Field(
        default=None,
        description="Restrict the search to a single uploaded document.",
    )


class DocumentSearchMatch(BaseModel):
    lease_id: str
    lease_name: str | None = None
    attachment_id: str | None = None
    source_filename: str
    chunk_index: int | None = None
    snippet: str
    score: float
    match_type: str


class DocumentSearchResponse(BaseModel):
    query: str
    matches: list[DocumentSearchMatch]


class DocumentTextResponse(BaseModel):
    attachment_id: str
    source_filename: str
    content_type: str | None = None
    text: str | None = None
    extractable: bool


class ReindexResponse(BaseModel):
    lease_id: str
    chunks_indexed: int


class IndexedDocument(BaseModel):
    attachment_id: str | None = None
    source_filename: str
    chunk_count: int


class IndexedDocumentsResponse(BaseModel):
    lease_id: str
    documents: list[IndexedDocument]


async def _get_lease_or_404(db: AsyncSession, lease_id: uuid.UUID, user: User) -> Lease:
    lease = (
        await db.execute(
            select(Lease).where(
                Lease.id == lease_id,
                Lease.is_deleted.is_(False),
                Lease.organization_id == user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if lease is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")
    return lease


@router.post("/document-search", response_model=DocumentSearchResponse)
async def search_all_lease_documents(
    payload: DocumentSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search document text across all of the organization's leases."""
    matches = await document_search_service.search_documents(
        db,
        organization_id=current_user.organization_id,
        query=payload.query,
        limit=payload.limit,
    )
    await usage_service.record_event(
        db, current_user.organization_id, "document_search"
    )
    return DocumentSearchResponse(query=payload.query, matches=matches)


@router.post("/{lease_id}/document-search", response_model=DocumentSearchResponse)
async def search_lease_documents(
    lease_id: uuid.UUID,
    payload: DocumentSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search document text within a single lease's attachments.

    When ``attachment_id`` is supplied the search is scoped to that one
    document, letting the caller pick which uploaded document to search.
    """
    await _get_lease_or_404(db, lease_id, current_user)
    matches = await document_search_service.search_documents(
        db,
        organization_id=current_user.organization_id,
        query=payload.query,
        lease_id=lease_id,
        attachment_id=payload.attachment_id,
        limit=payload.limit,
    )
    await usage_service.record_event(
        db, current_user.organization_id, "document_search"
    )
    return DocumentSearchResponse(query=payload.query, matches=matches)


@router.get(
    "/{lease_id}/documents",
    response_model=IndexedDocumentsResponse,
)
async def list_lease_indexed_documents(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the lease's searchable (indexed) documents for the search picker."""
    await _get_lease_or_404(db, lease_id, current_user)
    documents = await document_search_service.list_indexed_documents(
        db, lease_id=lease_id, organization_id=current_user.organization_id
    )
    return IndexedDocumentsResponse(
        lease_id=str(lease_id),
        documents=[IndexedDocument(**doc) for doc in documents],
    )


@router.get(
    "/{lease_id}/documents/{attachment_id}/text",
    response_model=DocumentTextResponse,
)
async def get_lease_document_text(
    lease_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the full extracted text of a lease attachment for previewing.

    Powers the search preview pane: the client highlights the query terms in the
    returned text. ``text`` is null with ``extractable=false`` when the document
    type cannot be extracted (the caller should fall back to the snippet).
    """
    lease = await _get_lease_or_404(db, lease_id, current_user)
    result = await document_search_service.get_document_text(
        db, lease=lease, attachment_id=attachment_id
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return DocumentTextResponse(**result)


@router.post("/{lease_id}/reindex-documents", response_model=ReindexResponse)
async def reindex_lease_documents(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    """(Re)build the search index for a lease's existing attachments."""
    lease = await _get_lease_or_404(db, lease_id, current_user)
    count = await document_search_service.reindex_lease_documents(db, lease)
    return ReindexResponse(lease_id=str(lease_id), chunks_indexed=count)

"""Semantic + keyword search over documents attached to leases.

Pipeline:

1. **Index** — when a document is attached to a lease its text is extracted
   (:mod:`app.services.document_extraction`), split into overlapping chunks, and
   (when Gemini is configured) embedded. Chunks are stored in
   ``lease_document_chunks`` with their embedding vector (JSONB).
2. **Search** — a query is embedded and ranked against stored chunk embeddings
   using cosine similarity computed in pure Python (no ``pgvector`` needed). When
   AI is unconfigured, or no embedded chunks exist, it falls back to a keyword
   ``ILIKE`` scan so the feature still works.

All operations are organization-scoped.
"""
from __future__ import annotations

import logging
import math
import re
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.lease import Lease
from app.models.lease_document_chunk import LeaseDocumentChunk
from app.services import ai_service, document_extraction

logger = logging.getLogger(__name__)

# Chunking parameters (characters). Chunks overlap so a match that straddles a
# boundary is still captured in at least one chunk.
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
MAX_CHUNKS_PER_DOCUMENT = 400


def chunk_text(text: str) -> list[str]:
    """Split ``text`` into overlapping, non-empty chunks."""
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    for start in range(0, len(text), step):
        piece = text[start : start + CHUNK_SIZE].strip()
        if piece:
            chunks.append(piece)
        if len(chunks) >= MAX_CHUNKS_PER_DOCUMENT:
            break
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _match_position(content: str, query: str) -> int:
    """Return the index of the first query term found in ``content`` (or 0)."""
    lowered = content.lower()
    for term in query.lower().split():
        pos = lowered.find(term)
        if pos != -1:
            return pos
    return 0


def _snippet(content: str, query: str, max_chars: int = 2000) -> str:
    """Return the full paragraph of ``content`` that contains the match.

    Rather than a fixed-width window centred on the match, this returns the
    entire paragraph the match falls in so the result is readable in context.
    A paragraph is the block of text delimited by blank lines; when the text has
    no blank lines (e.g. Word documents whose paragraphs are joined by single
    newlines) each newline is treated as a paragraph boundary instead. Internal
    line breaks are collapsed to single spaces for display, and an over-long
    paragraph is trimmed around the match so the snippet stays bounded.
    """
    content = content or ""
    if not content.strip():
        return ""

    pos = _match_position(content, query)

    # Prefer blank-line paragraph boundaries; fall back to single newlines when
    # the text has none (so Word-style single-newline paragraphs still split).
    separators = list(re.finditer(r"\n[ \t]*\n+", content))
    if not separators:
        separators = list(re.finditer(r"\n+", content))

    start = 0
    end = len(content)
    for m in separators:
        if m.start() <= pos:
            start = m.end()
        else:
            end = m.start()
            break

    paragraph = re.sub(r"\s+", " ", content[start:end]).strip()
    if not paragraph:
        paragraph = re.sub(r"\s+", " ", content).strip()

    if len(paragraph) > max_chars:
        # Re-locate the match inside the collapsed paragraph and centre a window
        # on it so the returned snippet remains bounded.
        rel = _match_position(paragraph, query)
        window_start = max(0, rel - max_chars // 2)
        window_end = min(len(paragraph), window_start + max_chars)
        prefix = "…" if window_start > 0 else ""
        suffix = "…" if window_end < len(paragraph) else ""
        paragraph = f"{prefix}{paragraph[window_start:window_end].strip()}{suffix}"

    return paragraph


async def index_attachment(
    db: AsyncSession,
    *,
    lease: Lease,
    attachment: Attachment,
    content: bytes,
) -> int:
    """Extract, chunk, (optionally) embed and store a lease attachment's text.

    Returns the number of chunks indexed. Best-effort: returns 0 (and indexes
    nothing) for document types whose text cannot be extracted. Embeddings are
    skipped gracefully when Gemini is not configured, leaving chunks
    keyword-searchable.
    """
    if not document_extraction.is_text_extractable(attachment.original_filename):
        return 0
    try:
        text = document_extraction.extract_text(content, attachment.original_filename)
    except document_extraction.DocumentExtractionError as exc:
        logger.info("Skipping document index for %s: %s", attachment.original_filename, exc)
        return 0

    chunks = chunk_text(text)
    if not chunks:
        return 0

    embeddings: list[list[float]] | None = None
    if ai_service.is_configured():
        try:
            embeddings = await ai_service.embed_texts(chunks)
        except ai_service.AIError as exc:
            logger.warning("Embedding failed for %s; storing keyword-only: %s",
                           attachment.original_filename, exc)
            embeddings = None

    # Replace any existing chunks for this attachment (idempotent re-index).
    await db.execute(
        delete(LeaseDocumentChunk).where(
            LeaseDocumentChunk.attachment_id == attachment.id
        )
    )
    for idx, piece in enumerate(chunks):
        db.add(
            LeaseDocumentChunk(
                organization_id=lease.organization_id,
                lease_id=lease.id,
                attachment_id=attachment.id,
                source_filename=attachment.original_filename,
                chunk_index=idx,
                content=piece,
                embedding=embeddings[idx] if embeddings else None,
            )
        )
    await db.commit()
    return len(chunks)


async def search_documents(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    query: str,
    lease_id: uuid.UUID | None = None,
    attachment_id: uuid.UUID | None = None,
    limit: int = 10,
    collapse_per_lease: bool | None = None,
) -> list[dict]:
    """Search indexed lease document chunks for ``query``.

    Uses semantic (embedding) ranking when AI is configured and embedded chunks
    exist; otherwise falls back to a keyword ``ILIKE`` scan.

    When ``attachment_id`` is supplied the search is restricted to that single
    uploaded document, so the caller can pick which document to search when a
    lease has several attached.

    By default results are grouped so at most one (best) match per lease is
    returned. When ``collapse_per_lease`` is ``False`` — which is the implicit
    default for a single-lease search — every matching chunk is returned so the
    caller can show multiple hits within the same document and navigate between
    them. Pass ``collapse_per_lease`` explicitly to override the default.
    """
    query = (query or "").strip()
    if not query:
        return []

    if collapse_per_lease is None:
        # A single-lease (or single-document) search shows every hit; portfolio
        # search collapses to one best match per lease.
        collapse_per_lease = lease_id is None and attachment_id is None

    query_embedding: list[float] | None = None
    if ai_service.is_configured():
        try:
            vectors = await ai_service.embed_texts([query])
            query_embedding = vectors[0] if vectors else None
        except ai_service.AIError as exc:
            logger.info("Query embedding unavailable, using keyword search: %s", exc)
            query_embedding = None

    if query_embedding is not None:
        rows = await _semantic_rank(
            db,
            organization_id=organization_id,
            query=query,
            query_embedding=query_embedding,
            lease_id=lease_id,
            attachment_id=attachment_id,
            limit=limit,
            collapse_per_lease=collapse_per_lease,
        )
        if rows:
            return rows
        # Fall through to keyword search when nothing was embedded yet.

    return await _keyword_rank(
        db,
        organization_id=organization_id,
        query=query,
        lease_id=lease_id,
        attachment_id=attachment_id,
        limit=limit,
        collapse_per_lease=collapse_per_lease,
    )


async def _semantic_rank(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    query: str,
    query_embedding: list[float],
    lease_id: uuid.UUID | None,
    attachment_id: uuid.UUID | None,
    limit: int,
    collapse_per_lease: bool,
) -> list[dict]:
    stmt = select(LeaseDocumentChunk).where(
        LeaseDocumentChunk.embedding.isnot(None)
    )
    if organization_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.organization_id == organization_id)
    if lease_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.lease_id == lease_id)
    if attachment_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.attachment_id == attachment_id)
    chunks = (await db.execute(stmt)).scalars().all()
    if not chunks:
        return []

    scored = []
    for chunk in chunks:
        score = _cosine(query_embedding, chunk.embedding or [])
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return await _hydrate_matches(
        db, scored, query, limit, mode="semantic", collapse_per_lease=collapse_per_lease
    )


async def _keyword_rank(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    query: str,
    lease_id: uuid.UUID | None,
    attachment_id: uuid.UUID | None,
    limit: int,
    collapse_per_lease: bool,
) -> list[dict]:
    # ``query`` is guaranteed non-empty by ``search_documents``. Match any of the
    # individual words; fall back to the whole phrase only if splitting yields
    # nothing (e.g. punctuation-only input).
    words = query.split()
    if words:
        word_filters = [LeaseDocumentChunk.content.ilike(f"%{w}%") for w in words]
    else:
        word_filters = [LeaseDocumentChunk.content.ilike(f"%{query}%")]
    stmt = select(LeaseDocumentChunk).where(or_(*word_filters))
    if organization_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.organization_id == organization_id)
    if lease_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.lease_id == lease_id)
    if attachment_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.attachment_id == attachment_id)
    stmt = stmt.limit(limit * 10)
    chunks = (await db.execute(stmt)).scalars().all()

    terms = [w.lower() for w in words]

    def keyword_score(content: str) -> int:
        lowered = content.lower()
        return sum(lowered.count(t) for t in terms) if terms else lowered.count(query.lower())

    scored = [(keyword_score(c.content), c) for c in chunks]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return await _hydrate_matches(
        db, scored, query, limit, mode="keyword", collapse_per_lease=collapse_per_lease
    )


async def _hydrate_matches(
    db: AsyncSession,
    scored: list[tuple[float, LeaseDocumentChunk]],
    query: str,
    limit: int,
    *,
    mode: str,
    collapse_per_lease: bool,
) -> list[dict]:
    """Hydrate scored chunks into result dicts, with optional per-lease collapse.

    When ``collapse_per_lease`` is true at most one (best) match per lease is
    returned. Otherwise every scored chunk is returned (capped at ``limit``) so a
    single document can surface multiple hits the caller can navigate between.
    """
    if collapse_per_lease:
        best: dict[uuid.UUID, tuple[float, LeaseDocumentChunk]] = {}
        for score, chunk in scored:
            existing = best.get(chunk.lease_id)
            if existing is None or score > existing[0]:
                best[chunk.lease_id] = (score, chunk)
        top = sorted(best.values(), key=lambda x: x[0], reverse=True)[:limit]
    else:
        top = scored[:limit]

    if not top:
        return []

    lease_ids = [chunk.lease_id for _, chunk in top]
    leases = (
        await db.execute(select(Lease).where(Lease.id.in_(lease_ids)))
    ).scalars().all()
    lease_by_id = {lease.id: lease for lease in leases}

    results = []
    for score, chunk in top:
        lease = lease_by_id.get(chunk.lease_id)
        results.append(
            {
                "lease_id": str(chunk.lease_id),
                "lease_name": getattr(lease, "lease_name", None) if lease else None,
                "attachment_id": str(chunk.attachment_id) if chunk.attachment_id else None,
                "source_filename": chunk.source_filename,
                "chunk_index": chunk.chunk_index,
                "snippet": _snippet(chunk.content, query),
                "score": round(float(score), 4),
                "match_type": mode,
            }
        )
    return results


async def get_document_text(
    db: AsyncSession,
    *,
    lease: Lease,
    attachment_id: uuid.UUID,
) -> dict | None:
    """Return the full extracted text of one of ``lease``'s attachments.

    Used to drive the search preview pane: the document's plain text is returned
    so the client can render it and highlight the query terms. Returns ``None``
    when the attachment does not belong to the lease. ``text`` is ``None`` (with
    ``extractable`` false) when the document type cannot be extracted or the
    underlying file is missing, so the caller can fall back to the snippet.
    """
    from pathlib import Path

    from app.config import settings

    attachment = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.entity_type == "lease",
                Attachment.entity_id == lease.id,
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        return None

    base = {
        "attachment_id": str(attachment.id),
        "source_filename": attachment.original_filename,
        "content_type": attachment.content_type,
    }

    if not document_extraction.is_text_extractable(attachment.original_filename):
        return {**base, "text": None, "extractable": False}

    path = Path(settings.UPLOAD_DIR) / attachment.entity_type / attachment.stored_filename
    if not path.exists():
        return {**base, "text": None, "extractable": False}

    try:
        content = path.read_bytes()
        text = document_extraction.extract_text(content, attachment.original_filename)
    except (OSError, document_extraction.DocumentExtractionError) as exc:
        logger.info("Could not extract preview text for %s: %s", attachment.original_filename, exc)
        return {**base, "text": None, "extractable": False}

    return {**base, "text": text, "extractable": True}


async def list_indexed_documents(
    db: AsyncSession,
    *,
    lease_id: uuid.UUID,
    organization_id: uuid.UUID | None,
) -> list[dict]:
    """Return the distinct documents that have been indexed for ``lease_id``.

    Powers the "search in" document picker: only documents with searchable
    indexed text are listed, each with its attachment id, filename and the
    number of indexed chunks. Documents whose text could not be extracted (and
    so were never indexed) are intentionally omitted because they are not
    searchable.
    """
    stmt = (
        select(
            LeaseDocumentChunk.attachment_id,
            # All chunks for a given attachment share the same source_filename
            # (set once from the attachment in ``index_attachment``), so any
            # aggregate is equivalent; ``min`` makes the grouped select valid.
            func.min(LeaseDocumentChunk.source_filename).label("source_filename"),
            func.count(LeaseDocumentChunk.id).label("chunk_count"),
        )
        .where(LeaseDocumentChunk.lease_id == lease_id)
        .group_by(LeaseDocumentChunk.attachment_id)
    )
    if organization_id is not None:
        stmt = stmt.where(LeaseDocumentChunk.organization_id == organization_id)

    rows = (await db.execute(stmt)).all()
    documents = [
        {
            "attachment_id": str(attachment_id) if attachment_id else None,
            "source_filename": source_filename,
            "chunk_count": int(chunk_count),
        }
        for attachment_id, source_filename, chunk_count in rows
    ]
    documents.sort(key=lambda d: (d["source_filename"] or "").lower())
    return documents


async def reindex_lease_documents(db: AsyncSession, lease: Lease) -> int:
    """(Re)index all extractable documents attached to ``lease``.

    Reads each lease attachment from disk, extracts and stores chunks. Returns
    the total number of chunks indexed. Used for backfilling existing files.
    """
    from pathlib import Path

    from app.config import settings

    attachments = (
        await db.execute(
            select(Attachment).where(
                Attachment.entity_type == "lease",
                Attachment.entity_id == lease.id,
            )
        )
    ).scalars().all()

    total = 0
    for attachment in attachments:
        path = Path(settings.UPLOAD_DIR) / attachment.entity_type / attachment.stored_filename
        if not path.exists():
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            logger.warning("Could not read %s for indexing: %s", path, exc)
            continue
        total += await index_attachment(db, lease=lease, attachment=attachment, content=content)
    return total

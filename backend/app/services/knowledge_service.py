"""Portfolio knowledge index + retrieval for the AI assistant (Phase 3).

This generalizes the lease-document semantic search to the whole portfolio. It
builds an organization-scoped index of short text chunks describing maintenance
tickets, leases, and lease abstracts (:class:`~app.models.knowledge_chunk.
KnowledgeChunk`) and answers retrieval queries against both that index *and* the
existing lease-document chunks.

Design mirrors :mod:`app.services.document_search_service`:

* **Embeddings** are computed with Gemini when configured and stored as JSONB.
  Cosine similarity is computed in Python — no ``pgvector`` extension required.
* **Graceful degradation** — when AI is unconfigured (or nothing is embedded
  yet) retrieval falls back to a keyword ``ILIKE`` scan so the feature still
  returns useful context.
* All operations are organization-scoped.

Indexing is best-effort and idempotent: :func:`reindex_organization` replaces an
org's chunks wholesale, so it can be run repeatedly (e.g. from the scheduler or
an explicit admin action) without duplicating rows.
"""
from __future__ import annotations

import logging
import math
import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_chunk import (
    SOURCE_LEASE,
    SOURCE_LEASE_ABSTRACT,
    SOURCE_TICKET,
    KnowledgeChunk,
)
from app.models.lease import Lease
from app.models.lease_abstract import LeaseAbstractClause
from app.models.lease_document_chunk import LeaseDocumentChunk
from app.models.maintenance_ticket import MaintenanceTicket
from app.services import ai_service

logger = logging.getLogger(__name__)

# A knowledge chunk is a compact, self-contained description of one record, so
# it is kept well under the embedding char cap and rarely needs splitting.
MAX_CHUNK_CHARS = 4000
# Bound how many source records of each kind are indexed per org per run.
MAX_RECORDS_PER_KIND = 5000


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


# ── Source → text builders ────────────────────────────────────────────────────

def _ticket_text(ticket: MaintenanceTicket) -> str:
    parts = [
        f"Maintenance ticket: {ticket.subject}",
        f"Status: {ticket.status}",
        f"Priority: {ticket.priority}",
    ]
    category = getattr(ticket, "category", None)
    if category is not None and getattr(category, "name", None):
        parts.append(f"Category: {category.name}")
    vendor = getattr(ticket, "vendor", None)
    if vendor is not None and getattr(vendor, "company_name", None):
        parts.append(f"Assigned vendor: {vendor.company_name}")
    if ticket.description:
        parts.append(f"Description: {ticket.description}")
    if ticket.vendor_completion_notes:
        parts.append(f"Completion notes: {ticket.vendor_completion_notes}")
    return _clean(". ".join(parts))[:MAX_CHUNK_CHARS]


def _lease_text(lease: Lease) -> str:
    parts = [f"Lease: {lease.lease_name}"]
    if lease.lessor_name:
        parts.append(f"Lessor: {lease.lessor_name}")
    if lease.lease_commencement_date:
        parts.append(f"Commencement: {lease.lease_commencement_date}")
    if lease.lease_expiration:
        parts.append(f"Expiration: {lease.lease_expiration}")
    if lease.notice_period:
        parts.append(f"Notice period: {lease.notice_period}")
    if lease.lease_notice_date:
        parts.append(f"Notice date: {lease.lease_notice_date}")
    if lease.payment_amount is not None:
        freq = lease.payment_frequency or "period"
        parts.append(f"Payment: {lease.payment_amount} per {freq}")
    if lease.lease_classification:
        parts.append(f"Classification: {lease.lease_classification}")
    if lease.accounting_standard:
        parts.append(f"Accounting standard: {lease.accounting_standard}")
    return _clean(". ".join(parts))[:MAX_CHUNK_CHARS]


def _abstract_text(clause: LeaseAbstractClause, lease_name: str | None) -> str:
    label = lease_name or "lease"
    parts = [f"Lease abstract clause '{clause.category_key}' for {label}"]
    content = clause.content or {}
    if isinstance(content, dict):
        for key, value in content.items():
            if value in (None, "", [], {}):
                continue
            parts.append(f"{key}: {value}")
    if clause.notes:
        parts.append(f"Notes: {clause.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


# ── Indexing ──────────────────────────────────────────────────────────────────

async def _collect_chunks(
    db: AsyncSession, organization_id: uuid.UUID
) -> list[dict]:
    """Build (un-embedded) chunk dicts for every indexable record in an org."""
    chunks: list[dict] = []

    tickets = (
        await db.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.organization_id == organization_id,
                MaintenanceTicket.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for ticket in tickets:
        chunks.append(
            {
                "source_type": SOURCE_TICKET,
                "source_id": ticket.id,
                "title": f"Ticket: {ticket.subject}",
                "reference": f"maintenance/{ticket.id}",
                "content": _ticket_text(ticket),
            }
        )

    leases = (
        await db.execute(
            select(Lease)
            .where(
                Lease.organization_id == organization_id,
                Lease.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    lease_name_by_id = {lease.id: lease.lease_name for lease in leases}
    for lease in leases:
        chunks.append(
            {
                "source_type": SOURCE_LEASE,
                "source_id": lease.id,
                "title": f"Lease: {lease.lease_name}",
                "reference": f"leases/{lease.id}",
                "content": _lease_text(lease),
            }
        )

    clauses = (
        await db.execute(
            select(LeaseAbstractClause)
            .where(LeaseAbstractClause.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for clause in clauses:
        lease_name = lease_name_by_id.get(clause.lease_id)
        text = _abstract_text(clause, lease_name)
        chunks.append(
            {
                "source_type": SOURCE_LEASE_ABSTRACT,
                "source_id": clause.lease_id,
                "title": f"Abstract '{clause.category_key}'"
                + (f" — {lease_name}" if lease_name else ""),
                "reference": f"leases/{clause.lease_id}",
                "content": text,
            }
        )

    # Drop empty-content chunks (nothing useful to embed or match).
    return [c for c in chunks if c["content"]]


async def reindex_organization(
    db: AsyncSession, organization_id: uuid.UUID
) -> int:
    """Rebuild the knowledge index for one organization. Returns chunk count.

    Idempotent: deletes the org's existing chunks and re-inserts a fresh set.
    Embeddings are added when Gemini is configured; otherwise chunks are stored
    keyword-only so retrieval still works.
    """
    chunks = await _collect_chunks(db, organization_id)

    embeddings: list[list[float]] | None = None
    if chunks and ai_service.is_configured():
        try:
            embeddings = await ai_service.embed_texts([c["content"] for c in chunks])
        except ai_service.AIError as exc:
            logger.warning(
                "Knowledge embedding failed for org %s; storing keyword-only: %s",
                organization_id,
                exc,
            )
            embeddings = None

    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.organization_id == organization_id
        )
    )
    for idx, chunk in enumerate(chunks):
        db.add(
            KnowledgeChunk(
                organization_id=organization_id,
                source_type=chunk["source_type"],
                source_id=chunk["source_id"],
                title=chunk["title"][:500],
                reference=chunk["reference"],
                chunk_index=0,
                content=chunk["content"],
                embedding=embeddings[idx] if embeddings else None,
            )
        )
    await db.commit()
    return len(chunks)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _normalize_knowledge(score: float, chunk: KnowledgeChunk, mode: str) -> dict:
    return {
        "source_type": chunk.source_type,
        "source_id": str(chunk.source_id),
        "title": chunk.title,
        "reference": chunk.reference,
        "content": chunk.content,
        "score": round(float(score), 4),
        "match_type": mode,
    }


def _normalize_document(
    score: float, chunk: LeaseDocumentChunk, lease_name: str | None, mode: str
) -> dict:
    label = chunk.source_filename or "document"
    if lease_name:
        label = f"{label} — {lease_name}"
    return {
        "source_type": "lease_document",
        "source_id": str(chunk.lease_id),
        "title": label,
        "reference": f"leases/{chunk.lease_id}",
        "content": chunk.content,
        "score": round(float(score), 4),
        "match_type": mode,
    }


async def retrieve(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> list[dict]:
    """Return the most relevant portfolio chunks for ``query`` (org-scoped).

    Combines the generalized knowledge index with the existing lease-document
    chunks. Uses semantic (embedding) ranking when AI is configured and embedded
    chunks exist; otherwise falls back to a keyword ``ILIKE`` scan.
    """
    query = (query or "").strip()
    if not query:
        return []

    query_embedding: list[float] | None = None
    if ai_service.is_configured():
        try:
            vectors = await ai_service.embed_texts([query])
            query_embedding = vectors[0] if vectors else None
        except ai_service.AIError as exc:
            logger.info("Query embedding unavailable, using keyword search: %s", exc)
            query_embedding = None

    if query_embedding is not None:
        results = await _semantic_retrieve(
            db, organization_id=organization_id, query_embedding=query_embedding, limit=limit
        )
        if results:
            return results
        # Fall through to keyword search when nothing is embedded yet.

    return await _keyword_retrieve(
        db, organization_id=organization_id, query=query, limit=limit
    )


async def _lease_names(db: AsyncSession, lease_ids: set[uuid.UUID]) -> dict:
    if not lease_ids:
        return {}
    leases = (
        await db.execute(select(Lease).where(Lease.id.in_(lease_ids)))
    ).scalars().all()
    return {lease.id: lease.lease_name for lease in leases}


async def _semantic_retrieve(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query_embedding: list[float],
    limit: int,
) -> list[dict]:
    scored: list[tuple[float, str, object]] = []

    k_chunks = (
        await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.organization_id == organization_id,
                KnowledgeChunk.embedding.isnot(None),
            )
        )
    ).scalars().all()
    for chunk in k_chunks:
        scored.append((_cosine(query_embedding, chunk.embedding or []), "knowledge", chunk))

    d_chunks = (
        await db.execute(
            select(LeaseDocumentChunk).where(
                LeaseDocumentChunk.organization_id == organization_id,
                LeaseDocumentChunk.embedding.isnot(None),
            )
        )
    ).scalars().all()
    for chunk in d_chunks:
        scored.append((_cosine(query_embedding, chunk.embedding or []), "document", chunk))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return await _hydrate(db, top, mode="semantic")


async def _keyword_retrieve(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict]:
    words = query.split()
    terms = [w.lower() for w in words] or [query.lower()]

    def keyword_score(content: str) -> int:
        lowered = (content or "").lower()
        return sum(lowered.count(t) for t in terms)

    scored: list[tuple[float, str, object]] = []

    k_filters = [KnowledgeChunk.content.ilike(f"%{w}%") for w in (words or [query])]
    k_chunks = (
        await db.execute(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.organization_id == organization_id,
                or_(*k_filters),
            )
            .limit(limit * 10)
        )
    ).scalars().all()
    for chunk in k_chunks:
        scored.append((keyword_score(chunk.content), "knowledge", chunk))

    d_filters = [LeaseDocumentChunk.content.ilike(f"%{w}%") for w in (words or [query])]
    d_chunks = (
        await db.execute(
            select(LeaseDocumentChunk)
            .where(
                LeaseDocumentChunk.organization_id == organization_id,
                or_(*d_filters),
            )
            .limit(limit * 10)
        )
    ).scalars().all()
    for chunk in d_chunks:
        scored.append((keyword_score(chunk.content), "document", chunk))

    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return await _hydrate(db, top, mode="keyword")


async def _hydrate(
    db: AsyncSession, top: list[tuple[float, str, object]], *, mode: str
) -> list[dict]:
    doc_lease_ids = {
        chunk.lease_id for _, kind, chunk in top if kind == "document"
    }
    lease_names = await _lease_names(db, doc_lease_ids)

    results: list[dict] = []
    for score, kind, chunk in top:
        if kind == "knowledge":
            results.append(_normalize_knowledge(score, chunk, mode))
        else:
            results.append(
                _normalize_document(score, chunk, lease_names.get(chunk.lease_id), mode)
            )
    return results

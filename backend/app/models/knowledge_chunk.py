"""Generalized, organization-scoped embedding index for the portfolio assistant.

Phase 3 of the AI-automation roadmap (RAG portfolio assistant) generalizes the
lease-document-only :class:`~app.models.lease_document_chunk.LeaseDocumentChunk`
index to the rest of the portfolio — maintenance tickets, leases, lease
abstracts, offices, landlords, vendors, management companies, HVAC contracts,
office transitions, and insurance certificates — so a single natural-language
question can be answered against the whole organization rather than a few
specific topics.

Each row is one searchable text chunk derived from a source record. As with
lease document chunks, the ``embedding`` column stores the raw float vector as
JSONB and cosine similarity is computed in Python, so **no ``pgvector`` extension
is required**; when no embedding is available the chunk stays keyword-searchable
via ``content``. ``pgvector`` was evaluated and intentionally deferred: it would
require a DB extension that the fresh-DB ``create_all``/``stamp`` bootstrap path
cannot guarantee, and the in-Python cosine + keyword fallback already powers the
existing document search at the platform's current scale.
"""
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Source kinds indexed into the shared knowledge index.
SOURCE_TICKET = "ticket"
SOURCE_LEASE = "lease"
SOURCE_LEASE_ABSTRACT = "lease_abstract"
SOURCE_OFFICE = "office"
SOURCE_LANDLORD = "landlord"
SOURCE_VENDOR = "vendor"
SOURCE_MANAGEMENT_COMPANY = "management_company"
SOURCE_HVAC_CONTRACT = "hvac_contract"
SOURCE_TRANSITION = "office_transition"
SOURCE_INSURANCE_CERTIFICATE = "insurance_certificate"
# ``lease_document`` chunks live in their own (pre-existing) table and are merged
# into retrieval at query time rather than copied here.
KNOWLEDGE_SOURCE_TYPES = frozenset({
    SOURCE_TICKET,
    SOURCE_LEASE,
    SOURCE_LEASE_ABSTRACT,
    SOURCE_OFFICE,
    SOURCE_LANDLORD,
    SOURCE_VENDOR,
    SOURCE_MANAGEMENT_COMPANY,
    SOURCE_HVAC_CONTRACT,
    SOURCE_TRANSITION,
    SOURCE_INSURANCE_CERTIFICATE,
})


class KnowledgeChunk(TimestampMixin, Base):
    """A searchable text chunk derived from a portfolio record.

    ``source_type`` identifies the originating entity kind (see the module-level
    ``SOURCE_*`` constants) and ``source_id`` its primary key, so a citation can
    deep-link back to the record. ``title`` is a human-readable label shown in
    citations; ``reference`` is an optional client route hint (e.g.
    ``maintenance/{id}``). The index is rebuilt per organization by
    :mod:`app.services.knowledge_service`.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("idx_knowledge_chunks_org", "organization_id"),
        Index("idx_knowledge_chunks_source", "source_type", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Embedding vector stored as a JSON array of floats (nullable when AI is off).
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)

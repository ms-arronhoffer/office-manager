import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LeaseDocumentChunk(TimestampMixin, Base):
    """A searchable text chunk extracted from a document attached to any record.

    Attachments (PDF/DOCX/TXT) on any entity — leases, offices, vendors,
    landlords, tickets, etc. — are extracted to plain text, split into chunks,
    and (when AI is configured) embedded so the content can be searched
    semantically. The ``embedding`` column stores the raw float vector as JSONB;
    cosine similarity is computed in Python so no ``pgvector`` extension is
    required. When no embedding is available the chunk is still keyword-searchable
    via ``content``. ``entity_type``/``entity_id`` identify the source record so a
    citation can deep-link back; ``lease_id`` is retained (nullable) for the
    existing lease-document search UI. Every chunk is hard-scoped to one
    organization for strict, no-cross-org-intrusion retrieval.
    """

    __tablename__ = "lease_document_chunks"
    __table_args__ = (
        Index("idx_lease_doc_chunks_lease", "lease_id"),
        Index("idx_lease_doc_chunks_org", "organization_id"),
        Index("idx_lease_doc_chunks_attachment", "attachment_id"),
        Index("idx_lease_doc_chunks_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    # Source entity the document is attached to (lease, office, vendor, ...).
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Retained for the lease-document search UI; null for non-lease documents.
    lease_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=True
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), nullable=True
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Embedding vector stored as a JSON array of floats (nullable when AI is off).
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)

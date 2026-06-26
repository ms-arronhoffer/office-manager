import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LeaseDocumentChunk(TimestampMixin, Base):
    """A searchable text chunk extracted from a document attached to a lease.

    Lease attachments (PDF/DOCX/TXT) are extracted to plain text, split into
    chunks, and (when AI is configured) embedded so the content can be searched
    semantically. The ``embedding`` column stores the raw float vector as JSONB;
    cosine similarity is computed in Python so no ``pgvector`` extension is
    required. When no embedding is available the chunk is still keyword-searchable
    via ``content``.
    """

    __tablename__ = "lease_document_chunks"
    __table_args__ = (
        Index("idx_lease_doc_chunks_lease", "lease_id"),
        Index("idx_lease_doc_chunks_org", "organization_id"),
        Index("idx_lease_doc_chunks_attachment", "attachment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="CASCADE"), nullable=True
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Embedding vector stored as a JSON array of floats (nullable when AI is off).
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)

"""Lease Abstract clause storage.

A ``LeaseAbstractClause`` row holds the captured content for a single clause
category (see ``app.services.lease_abstract_catalog``) on a single lease. The
category schema lives in code; this table stores only the per-lease values,
completeness status, and free-text notes, keyed by ``category_key``.
"""
import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class LeaseAbstractClause(TimestampMixin, Base):
    __tablename__ = "lease_abstract_clauses"
    __table_args__ = (
        UniqueConstraint("lease_id", "category_key", name="uq_abstract_clause_lease_category"),
        Index("idx_abstract_clause_lease_id", "lease_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    category_key: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="needs_content", server_default="needs_content"
    )
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lease: Mapped["Lease"] = relationship()


from app.models.lease import Lease  # noqa: E402

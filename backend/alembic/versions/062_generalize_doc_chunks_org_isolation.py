"""Generalize document chunks to all entities + enforce strict org isolation.

Phase 1/2 of the per-org RAG corpus hardening:

* Adds ``entity_type``/``entity_id`` to ``lease_document_chunks`` so attachments
  on any record (offices, vendors, landlords, tickets, ...) — not just leases —
  can be indexed; ``lease_id`` is made nullable and existing rows are tagged
  ``entity_type='lease'``.
* Backfills NULL ``organization_id`` from parent records where possible, deletes
  any chunks that cannot be scoped to an org, and makes ``organization_id`` NOT
  NULL on ``knowledge_chunks`` and ``lease_document_chunks`` so no chunk can ever
  be retrieved without an org filter (cross-org intrusion is a failure).

Revision ID: 062
Revises: 061
"""
import sqlalchemy as sa
from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Generalize lease_document_chunks to any source entity ──────────────
    op.add_column(
        "lease_document_chunks",
        sa.Column("entity_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "lease_document_chunks",
        sa.Column("entity_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "idx_lease_doc_chunks_entity",
        "lease_document_chunks",
        ["entity_type", "entity_id"],
    )
    # Existing rows are all lease documents.
    op.execute(
        "UPDATE lease_document_chunks "
        "SET entity_type = 'lease', entity_id = lease_id "
        "WHERE entity_type IS NULL"
    )
    op.alter_column("lease_document_chunks", "lease_id", nullable=True)

    # ── Strict org isolation: backfill, prune orphans, enforce NOT NULL ────
    op.execute(
        "UPDATE lease_document_chunks c SET organization_id = l.organization_id "
        "FROM leases l WHERE c.organization_id IS NULL AND c.lease_id = l.id"
    )
    op.execute("DELETE FROM lease_document_chunks WHERE organization_id IS NULL")
    op.execute("DELETE FROM knowledge_chunks WHERE organization_id IS NULL")
    op.alter_column("lease_document_chunks", "organization_id", nullable=False)
    op.alter_column("knowledge_chunks", "organization_id", nullable=False)


def downgrade() -> None:
    op.alter_column("knowledge_chunks", "organization_id", nullable=True)
    op.alter_column("lease_document_chunks", "organization_id", nullable=True)
    # Restore lease_id to its original NOT NULL constraint (delete orphans first).
    op.execute("DELETE FROM lease_document_chunks WHERE lease_id IS NULL")
    op.alter_column("lease_document_chunks", "lease_id", nullable=False)
    op.drop_index("idx_lease_doc_chunks_entity", table_name="lease_document_chunks")
    op.drop_column("lease_document_chunks", "entity_id")
    op.drop_column("lease_document_chunks", "entity_type")

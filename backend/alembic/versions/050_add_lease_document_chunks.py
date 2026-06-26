"""Add lease_document_chunks for semantic/keyword document search.

Stores plain-text chunks extracted from documents attached to a lease, plus an
optional embedding vector (JSONB array of floats). Cosine similarity is computed
in Python so no pgvector extension is needed; when no embedding is present the
chunk remains keyword-searchable via its ``content`` column.

Revision ID: 050
Revises: 049
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lease_document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
        sa.Column(
            "lease_id",
            sa.Uuid(),
            sa.ForeignKey("leases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.Uuid(),
            sa.ForeignKey("attachments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_lease_doc_chunks_lease", "lease_document_chunks", ["lease_id"]
    )
    op.create_index(
        "idx_lease_doc_chunks_org", "lease_document_chunks", ["organization_id"]
    )
    op.create_index(
        "idx_lease_doc_chunks_attachment",
        "lease_document_chunks",
        ["attachment_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_lease_doc_chunks_attachment", table_name="lease_document_chunks")
    op.drop_index("idx_lease_doc_chunks_org", table_name="lease_document_chunks")
    op.drop_index("idx_lease_doc_chunks_lease", table_name="lease_document_chunks")
    op.drop_table("lease_document_chunks")

"""Add knowledge_chunks: generalized embedding index for the portfolio assistant.

Phase 3 of the AI-automation roadmap. Generalizes the lease-document-only chunk
index to maintenance tickets, leases, and lease abstracts so a single
natural-language question can be answered against the whole portfolio. Embeddings
are stored as a JSONB array of floats (cosine computed in Python; no pgvector
needed); chunks remain keyword-searchable via ``content`` when no embedding is
present.

Revision ID: 054
Revises: 053
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
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
    op.create_index("idx_knowledge_chunks_org", "knowledge_chunks", ["organization_id"])
    op.create_index(
        "idx_knowledge_chunks_source",
        "knowledge_chunks",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_chunks_source", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_org", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

"""Add lease abstract clauses table

Revision ID: 041
Revises: 040
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lease_abstract_clauses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("lease_id", sa.UUID(), nullable=False),
        sa.Column("category_key", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="needs_content"),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lease_id"], ["leases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_id", "category_key", name="uq_abstract_clause_lease_category"),
    )
    op.create_index(
        "ix_lease_abstract_clauses_organization_id",
        "lease_abstract_clauses",
        ["organization_id"],
    )
    op.create_index(
        "idx_abstract_clause_lease_id",
        "lease_abstract_clauses",
        ["lease_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_abstract_clause_lease_id", table_name="lease_abstract_clauses")
    op.drop_index(
        "ix_lease_abstract_clauses_organization_id", table_name="lease_abstract_clauses"
    )
    op.drop_table("lease_abstract_clauses")

"""Add admin_notes to organizations

Revision ID: 033
Revises: 032
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("admin_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "admin_notes")

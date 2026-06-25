"""add created_by_id to ticket_notes

Revision ID: 012
Revises: 011
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ticket_notes",
        sa.Column("created_by_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ticket_notes", "created_by_id")

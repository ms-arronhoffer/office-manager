"""add closed_at to maintenance_tickets

Revision ID: 016
Revises: 015
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "maintenance_tickets",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("maintenance_tickets", "closed_at")

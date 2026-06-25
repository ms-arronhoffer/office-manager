"""Add space & occupancy fields to offices

Revision ID: 026
Revises: 025
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("offices", sa.Column("total_sqft", sa.Numeric(12, 2), nullable=True))
    op.add_column("offices", sa.Column("usable_sqft", sa.Numeric(12, 2), nullable=True))
    op.add_column("offices", sa.Column("headcount_capacity", sa.Integer(), nullable=True))
    op.add_column("offices", sa.Column("current_headcount", sa.Integer(), nullable=True))
    op.add_column("offices", sa.Column("space_type", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("offices", "space_type")
    op.drop_column("offices", "current_headcount")
    op.drop_column("offices", "headcount_capacity")
    op.drop_column("offices", "usable_sqft")
    op.drop_column("offices", "total_sqft")

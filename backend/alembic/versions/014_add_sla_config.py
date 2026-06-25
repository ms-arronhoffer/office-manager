"""add SLA threshold config to site_settings

Revision ID: 014
Revises: 013
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("site_settings", sa.Column("sla_high_days", sa.Integer(), nullable=True))
    op.add_column("site_settings", sa.Column("sla_medium_days", sa.Integer(), nullable=True))
    op.add_column("site_settings", sa.Column("sla_low_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("site_settings", "sla_low_days")
    op.drop_column("site_settings", "sla_medium_days")
    op.drop_column("site_settings", "sla_high_days")

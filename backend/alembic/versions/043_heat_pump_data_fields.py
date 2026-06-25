"""Enrich heat pump data fields

Adds equipment specification and maintenance-tracking data points to HQ heat
pumps: refrigerant type, tonnage, SEER rating, filter size, warranty
expiration, last/next service dates, and lifecycle status.

Revision ID: 043
Revises: 042
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hq_heat_pumps", sa.Column("refrigerant_type", sa.String(50), nullable=True))
    op.add_column("hq_heat_pumps", sa.Column("tonnage", sa.Numeric(5, 2), nullable=True))
    op.add_column("hq_heat_pumps", sa.Column("seer_rating", sa.Numeric(5, 2), nullable=True))
    op.add_column("hq_heat_pumps", sa.Column("filter_size", sa.String(50), nullable=True))
    op.add_column("hq_heat_pumps", sa.Column("warranty_expiration", sa.Date(), nullable=True))
    op.add_column("hq_heat_pumps", sa.Column("last_service_date", sa.Date(), nullable=True))
    op.add_column("hq_heat_pumps", sa.Column("next_service_date", sa.Date(), nullable=True))
    op.add_column(
        "hq_heat_pumps",
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
    )


def downgrade() -> None:
    op.drop_column("hq_heat_pumps", "status")
    op.drop_column("hq_heat_pumps", "next_service_date")
    op.drop_column("hq_heat_pumps", "last_service_date")
    op.drop_column("hq_heat_pumps", "warranty_expiration")
    op.drop_column("hq_heat_pumps", "filter_size")
    op.drop_column("hq_heat_pumps", "seer_rating")
    op.drop_column("hq_heat_pumps", "tonnage")
    op.drop_column("hq_heat_pumps", "refrigerant_type")

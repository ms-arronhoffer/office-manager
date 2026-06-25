"""add space history table

Revision ID: 031
Revises: 030
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("office_id", sa.UUID(), sa.ForeignKey("offices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("snapshot_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_sqft", sa.Numeric(12, 2), nullable=True),
        sa.Column("usable_sqft", sa.Numeric(12, 2), nullable=True),
        sa.Column("headcount_capacity", sa.Integer(), nullable=True),
        sa.Column("current_headcount", sa.Integer(), nullable=True),
        sa.Column("space_type", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_space_history_office", "space_history", ["office_id"])
    op.create_index("idx_space_history_org_date", "space_history", ["organization_id", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("idx_space_history_org_date", table_name="space_history")
    op.drop_index("idx_space_history_office", table_name="space_history")
    op.drop_table("space_history")

"""add lease_options table for structured option tracking

Revision ID: 021
Revises: 020
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lease_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_type", sa.String(30), nullable=False),
        # option_type: renewal | expansion | termination | rofo | rofr | purchase
        sa.Column("exercise_window_start", sa.Date, nullable=True),
        sa.Column("exercise_window_end", sa.Date, nullable=True),
        sa.Column("notice_required_days", sa.Integer, nullable=True),
        sa.Column("new_term_months", sa.Integer, nullable=True),
        sa.Column("new_rent_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        # status: open | exercised | expired | waived
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_lease_options_lease_id", "lease_options", ["lease_id"])
    op.create_index("idx_lease_options_exercise_window_end", "lease_options", ["exercise_window_end"])


def downgrade() -> None:
    op.drop_index("idx_lease_options_exercise_window_end", table_name="lease_options")
    op.drop_index("idx_lease_options_lease_id", table_name="lease_options")
    op.drop_table("lease_options")

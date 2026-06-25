"""add lease renewals table

Revision ID: 019
Revises: 018
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lease_renewals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="in_progress"),
        sa.Column("target_expiration", sa.Date, nullable=True),
        sa.Column("new_rent_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_lease_renewals_lease_id", "lease_renewals", ["lease_id"])


def downgrade() -> None:
    op.drop_index("idx_lease_renewals_lease_id", table_name="lease_renewals")
    op.drop_table("lease_renewals")

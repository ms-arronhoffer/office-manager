"""Add usage_events table for metered AI/feature tracking.

Revision ID: 055
Revises: 054
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("feature", sa.String(length=50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("period_month", sa.String(length=7), nullable=False),
        sa.Column("meta", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_usage_org_period", "usage_events", ["organization_id", "period_month"])
    op.create_index("idx_usage_org_feature", "usage_events", ["organization_id", "feature"])


def downgrade() -> None:
    op.drop_index("idx_usage_org_feature", table_name="usage_events")
    op.drop_index("idx_usage_org_period", table_name="usage_events")
    op.drop_table("usage_events")

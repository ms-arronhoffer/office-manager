"""Add impersonation_sessions table for auditing super-admin impersonation.

Revision ID: 056
Revises: 055
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impersonation_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "admin_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "target_org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "target_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("target_user_email", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_impersonation_admin", "impersonation_sessions", ["admin_user_id"])
    op.create_index("ix_impersonation_org", "impersonation_sessions", ["target_org_id"])


def downgrade() -> None:
    op.drop_index("ix_impersonation_org", table_name="impersonation_sessions")
    op.drop_index("ix_impersonation_admin", table_name="impersonation_sessions")
    op.drop_table("impersonation_sessions")

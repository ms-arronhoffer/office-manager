"""Add entitlement_overrides JSON column to organizations.

Revision ID: 046
Revises: 045
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "entitlement_overrides",
            JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "past_due_since")
    op.drop_column("organizations", "entitlement_overrides")

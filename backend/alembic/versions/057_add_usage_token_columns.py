"""Add input/output token columns to usage_events.

Records per-call AI token consumption (input = prompt tokens, output =
candidate/completion tokens) so the super-admin console can monitor token usage
per org and enforce tier-based limits. Non-AI feature events keep these at 0.

Revision ID: 057
Revises: 056
"""
import sqlalchemy as sa
from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "usage_events",
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("usage_events", "output_tokens")
    op.drop_column("usage_events", "input_tokens")

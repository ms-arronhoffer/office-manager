"""Add payment_status to organizations and next_retry_at to webhook_deliveries

Revision ID: 032
Revises: 031
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── organizations.payment_status ─────────────────────────────────────────
    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "payment_status" not in org_cols:
        op.add_column(
            "organizations",
            sa.Column("payment_status", sa.String(20), nullable=False, server_default="active"),
        )

    # ── webhook_deliveries.next_retry_at ─────────────────────────────────────
    wh_cols = [c["name"] for c in inspector.get_columns("webhook_deliveries")]
    if "next_retry_at" not in wh_cols:
        op.add_column(
            "webhook_deliveries",
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    wh_cols = [c["name"] for c in inspector.get_columns("webhook_deliveries")]
    if "next_retry_at" in wh_cols:
        op.drop_column("webhook_deliveries", "next_retry_at")

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "payment_status" in org_cols:
        op.drop_column("organizations", "payment_status")

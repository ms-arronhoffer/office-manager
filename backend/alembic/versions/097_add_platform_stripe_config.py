"""Add platform-wide Stripe integration config

Adds ``platform_stripe_config`` — a single-row table holding the SaaS billing
Stripe credentials manageable from the super-admin console (Billing → Stripe
Integration), replacing the deploy-only ``STRIPE_*`` environment variables.
Secret values are encrypted at rest (see app.utils.crypto).

Idempotent: guards on table existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 097
Revises: 096
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "platform_stripe_config" in inspector.get_table_names():
        return
    op.create_table(
        "platform_stripe_config",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("secret_key_encrypted", sa.Text(), nullable=True),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("publishable_key", sa.String(255), nullable=True),
        sa.Column("price_id_pro", sa.String(255), nullable=True),
        sa.Column("price_id_enterprise", sa.String(255), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verify_ok", sa.Boolean(), nullable=True),
        sa.Column("last_verify_error", sa.Text(), nullable=True),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "platform_stripe_config" in inspector.get_table_names():
        op.drop_table("platform_stripe_config")

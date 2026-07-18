"""Add enterprise_activation_codes table

Enterprise is custom-priced per subscriber. A super-admin mints an opaque
activation code that maps to a bespoke Stripe Price (created under the platform
Enterprise Product); the org admin enters the code on the billing page to
self-activate their negotiated Enterprise plan. See
:mod:`app.models.enterprise_activation_code`.

Idempotent: guards on table existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 104
Revises: 103
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None

_TABLE = "enterprise_activation_codes"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in inspector.get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["redeemed_by_org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        op.f("ix_enterprise_activation_codes_code"), _TABLE, ["code"], unique=True
    )
    op.create_index(
        op.f("ix_enterprise_activation_codes_organization_id"),
        _TABLE,
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    op.drop_index(op.f("ix_enterprise_activation_codes_organization_id"), table_name=_TABLE)
    op.drop_index(op.f("ix_enterprise_activation_codes_code"), table_name=_TABLE)
    op.drop_table(_TABLE)

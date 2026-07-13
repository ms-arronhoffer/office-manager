"""Add cancel_at_period_end and current_period_end to organizations

Supports in-app subscription cancellation/downgrade: cancellation is
scheduled at the end of the current paid period (rather than revoking
access immediately), mirroring Stripe's ``cancel_at_period_end`` semantics.
``current_period_end`` is kept in sync from Stripe webhooks so the billing
page can tell the user exactly when access will end.

Idempotent: guards on column existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 103
Revises: 102
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "103"
down_revision = "102"
branch_labels = None
depends_on = None

_TABLE = "organizations"


def _columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    cols = _columns(inspector)
    if "cancel_at_period_end" not in cols:
        op.add_column(
            _TABLE,
            sa.Column(
                "cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    if "current_period_end" not in cols:
        op.add_column(_TABLE, sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    cols = _columns(inspector)
    if "current_period_end" in cols:
        op.drop_column(_TABLE, "current_period_end")
    if "cancel_at_period_end" in cols:
        op.drop_column(_TABLE, "cancel_at_period_end")

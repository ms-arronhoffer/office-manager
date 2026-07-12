"""Add Starter price id and Enterprise product id to platform Stripe config

The SaaS billing integration previously supported only Pro and Enterprise via a
fixed ``price_id_pro``/``price_id_enterprise`` pair. This migration:

* adds ``price_id_starter`` so the Starter plan can be sold through Stripe, and
* adds ``product_id_enterprise`` because Enterprise is now custom-priced per
  subscriber — every subscriber gets a bespoke price under a single Enterprise
  Product, which is how Enterprise subscriptions are identified in webhooks.

The legacy ``price_id_enterprise`` column is left in place (unused) so the
migration is non-destructive on long-lived databases.

Idempotent: guards on column existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 102
Revises: 101
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None

_TABLE = "platform_stripe_config"


def _columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    cols = _columns(inspector)
    if "price_id_starter" not in cols:
        op.add_column(_TABLE, sa.Column("price_id_starter", sa.String(255), nullable=True))
    if "product_id_enterprise" not in cols:
        op.add_column(_TABLE, sa.Column("product_id_enterprise", sa.String(255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    cols = _columns(inspector)
    if "product_id_enterprise" in cols:
        op.drop_column(_TABLE, "product_id_enterprise")
    if "price_id_starter" in cols:
        op.drop_column(_TABLE, "price_id_starter")

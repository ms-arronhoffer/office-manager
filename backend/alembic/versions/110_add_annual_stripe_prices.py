"""Add annual Core and Operations Stripe price IDs.

Revision ID: 110
Revises: 109
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None

_TABLE = "platform_stripe_config"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}
    if "price_id_starter_annual" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("price_id_starter_annual", sa.String(255), nullable=True),
        )
    if "price_id_pro_annual" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("price_id_pro_annual", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}
    if "price_id_pro_annual" in columns:
        op.drop_column(_TABLE, "price_id_pro_annual")
    if "price_id_starter_annual" in columns:
        op.drop_column(_TABLE, "price_id_starter_annual")
"""Replace site_settings.app_name with company info fields

The application's top-navigation brand name is now a fixed constant
(no longer admin-configurable), so ``app_name`` is dropped. In its place we
add company-specific fields (name, address, phone, email) used as the
company header on generated reports and shown in the side navigation.

Revision ID: 081b
Revises: 080
"""
import sqlalchemy as sa
from alembic import op

revision = "081b"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent guards: this migration was originally shipped as revision
    # ``081`` and later renamed to ``081b`` (to resolve a duplicate ``081``
    # revision / multiple-heads error). A database that already applied the
    # original ``081`` is stamped ``081`` — which now maps to a *different*
    # migration — so ``alembic upgrade head`` re-runs this one as ``081b`` and
    # would otherwise fail on ``column "company_name" already exists``. Inspect
    # the live schema (mirroring migration 081's pattern) and only apply the
    # parts that are still missing.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c["name"] for c in inspector.get_columns("site_settings")}

    if "company_name" not in columns:
        op.add_column(
            "site_settings",
            sa.Column("company_name", sa.String(length=200), nullable=False, server_default="Portfolio Desk"),
        )
    if "company_address" not in columns:
        op.add_column("site_settings", sa.Column("company_address", sa.Text(), nullable=True))
    if "company_phone" not in columns:
        op.add_column("site_settings", sa.Column("company_phone", sa.String(length=50), nullable=True))
    if "company_email" not in columns:
        op.add_column("site_settings", sa.Column("company_email", sa.String(length=320), nullable=True))
    if "app_name" in columns:
        op.execute("UPDATE site_settings SET company_name = app_name")
        op.drop_column("site_settings", "app_name")
    op.alter_column("site_settings", "company_name", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c["name"] for c in inspector.get_columns("site_settings")}

    if "app_name" not in columns:
        op.add_column(
            "site_settings",
            sa.Column("app_name", sa.String(length=200), nullable=False, server_default="Portfolio Desk"),
        )
        if "company_name" in columns:
            op.execute("UPDATE site_settings SET app_name = company_name")
        op.alter_column("site_settings", "app_name", server_default=None)
    for col in ("company_email", "company_phone", "company_address", "company_name"):
        if col in columns:
            op.drop_column("site_settings", col)

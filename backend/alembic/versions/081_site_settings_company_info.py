"""Replace site_settings.app_name with company info fields

The application's top-navigation brand name is now a fixed constant
(no longer admin-configurable), so ``app_name`` is dropped. In its place we
add company-specific fields (name, address, phone, email) used as the
company header on generated reports and shown in the side navigation.

Revision ID: 081
Revises: 080
"""
import sqlalchemy as sa
from alembic import op

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column("company_name", sa.String(length=200), nullable=False, server_default="Portfolio Desk"),
    )
    op.add_column("site_settings", sa.Column("company_address", sa.Text(), nullable=True))
    op.add_column("site_settings", sa.Column("company_phone", sa.String(length=50), nullable=True))
    op.add_column("site_settings", sa.Column("company_email", sa.String(length=320), nullable=True))
    op.execute("UPDATE site_settings SET company_name = app_name")
    op.drop_column("site_settings", "app_name")
    op.alter_column("site_settings", "company_name", server_default=None)


def downgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column("app_name", sa.String(length=200), nullable=False, server_default="Portfolio Desk"),
    )
    op.execute("UPDATE site_settings SET app_name = company_name")
    op.alter_column("site_settings", "app_name", server_default=None)
    op.drop_column("site_settings", "company_email")
    op.drop_column("site_settings", "company_phone")
    op.drop_column("site_settings", "company_address")
    op.drop_column("site_settings", "company_name")

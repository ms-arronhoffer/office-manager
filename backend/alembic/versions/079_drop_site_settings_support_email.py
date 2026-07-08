"""Drop site_settings.support_email in favor of the SUPPORT_EMAIL env var.

The support-request recipient address is no longer admin-configurable per
tenant; it's now a single platform-wide value read from the ``SUPPORT_EMAIL``
environment variable (see ``app.routers.support_requests``).

Revision ID: 079
Revises: 078
"""
import sqlalchemy as sa
from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("site_settings", "support_email")


def downgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column("support_email", sa.String(length=320), nullable=True),
    )

"""Add support requests table and site-settings support email.

Introduces the in-app Support Request channel:

* ``support_requests`` — org-scoped help submissions reviewed on the
  Administration → Support Requests page.
* ``site_settings.support_email`` — the address support requests are forwarded
  to.

Revision ID: 060
Revises: 059
"""
import sqlalchemy as sa
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("requester_user_id", sa.UUID(), nullable=True),
        sa.Column("requester_name", sa.String(length=255), nullable=True),
        sa.Column("requester_email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_requests_organization_id", "support_requests", ["organization_id"]
    )

    op.add_column(
        "site_settings",
        sa.Column("support_email", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "support_email")
    op.drop_index("ix_support_requests_organization_id", table_name="support_requests")
    op.drop_table("support_requests")

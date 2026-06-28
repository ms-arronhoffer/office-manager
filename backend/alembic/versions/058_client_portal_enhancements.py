"""Client portal: change requests + access lifecycle columns.

Adds:
* ``client_portal_accounts.last_active_at`` / ``revoked_at`` for the internal
  portal-status view and admin revocation.
* ``client_portal_change_requests`` table for the profile change-request /
  approval workflow.

Revision ID: 058
Revises: 057
"""
import sqlalchemy as sa
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_portal_accounts",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "client_portal_accounts",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "client_portal_change_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("proposed_changes", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_by_display_name", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["client_portal_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_portal_change_requests_organization_id",
        "client_portal_change_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_client_portal_change_requests_account_id",
        "client_portal_change_requests",
        ["account_id"],
    )
    op.create_index(
        "ix_client_portal_change_requests_entity_id",
        "client_portal_change_requests",
        ["entity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_portal_change_requests_entity_id",
        table_name="client_portal_change_requests",
    )
    op.drop_index(
        "ix_client_portal_change_requests_account_id",
        table_name="client_portal_change_requests",
    )
    op.drop_index(
        "ix_client_portal_change_requests_organization_id",
        table_name="client_portal_change_requests",
    )
    op.drop_table("client_portal_change_requests")
    op.drop_column("client_portal_accounts", "revoked_at")
    op.drop_column("client_portal_accounts", "last_active_at")

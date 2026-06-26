"""Add client_portal_accounts for landlord/management-company self-service portals.

Revision ID: 047
Revises: 046
"""
import sqlalchemy as sa
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_portal_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("signup_token", sa.String(length=64), nullable=True),
        sa.Column("signup_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("portal_token", sa.String(length=64), nullable=True),
        sa.Column("portal_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_client_portal_entity"),
        sa.UniqueConstraint("signup_token"),
        sa.UniqueConstraint("portal_token"),
    )
    op.create_index(
        "ix_client_portal_accounts_organization_id",
        "client_portal_accounts",
        ["organization_id"],
    )
    op.create_index(
        "ix_client_portal_accounts_entity_id",
        "client_portal_accounts",
        ["entity_id"],
    )
    op.create_index(
        "ix_client_portal_accounts_signup_token",
        "client_portal_accounts",
        ["signup_token"],
    )
    op.create_index(
        "ix_client_portal_accounts_portal_token",
        "client_portal_accounts",
        ["portal_token"],
    )


def downgrade() -> None:
    op.drop_index("ix_client_portal_accounts_portal_token", table_name="client_portal_accounts")
    op.drop_index("ix_client_portal_accounts_signup_token", table_name="client_portal_accounts")
    op.drop_index("ix_client_portal_accounts_entity_id", table_name="client_portal_accounts")
    op.drop_index("ix_client_portal_accounts_organization_id", table_name="client_portal_accounts")
    op.drop_table("client_portal_accounts")

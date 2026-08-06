"""Add organization-scoped integration provider settings.

Revision ID: 120
Revises: 119
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None


_PREDICATE = """
(
    current_setting('app.rls_bypass', true) = 'on'
    OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
)
"""


def upgrade() -> None:
    op.create_table(
        "organization_integration_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("settings_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verify_ok", sa.Boolean(), nullable=True),
        sa.Column("last_verify_error", sa.Text(), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('resident_payments', 'screening', 'plaid')",
            name="ck_org_integration_config_provider",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "provider", name="uq_org_integration_config_org_provider"
        ),
    )
    op.create_index(
        "ix_organization_integration_configs_organization_id",
        "organization_integration_configs",
        ["organization_id"],
    )
    op.execute(
        "ALTER TABLE organization_integration_configs ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE organization_integration_configs FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY organization_integration_configs_org_isolation "
        "ON organization_integration_configs "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    op.drop_table("organization_integration_configs")
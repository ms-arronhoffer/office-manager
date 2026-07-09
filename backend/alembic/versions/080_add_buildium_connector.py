"""Add Buildium migration connector tables

Adds the tables backing the Buildium -> Portfolio Desk migration connector
(Administration -> System & Data -> Buildium Migration):

  - ``buildium_connections``       — per-org API credentials (encrypted secret)
  - ``buildium_entity_maps``       — Buildium id -> local uuid crosswalk
  - ``buildium_gl_account_maps``   — Buildium GL account -> local GLAccount mapping
  - ``buildium_migration_runs``    — persisted status/progress for each run

Revision ID: 080
Revises: 079
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buildium_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False, server_default="https://api.buildium.com/v1"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verify_ok", sa.Boolean(), nullable=True),
        sa.Column("last_verify_error", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_buildium_connection_org"),
    )
    op.create_index(
        "ix_buildium_connections_organization_id", "buildium_connections", ["organization_id"]
    )

    op.create_table(
        "buildium_entity_maps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("buildium_id", sa.String(64), nullable=False),
        sa.Column("local_id", sa.UUID(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "entity_type", "buildium_id", name="uq_buildium_entity_map"
        ),
    )
    op.create_index(
        "ix_buildium_entity_maps_organization_id", "buildium_entity_maps", ["organization_id"]
    )
    op.create_index(
        "idx_buildium_entity_maps_local", "buildium_entity_maps", ["entity_type", "local_id"]
    )

    op.create_table(
        "buildium_gl_account_maps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("buildium_gl_account_id", sa.String(64), nullable=False),
        sa.Column("buildium_account_name", sa.String(255), nullable=True),
        sa.Column("buildium_account_type", sa.String(50), nullable=True),
        sa.Column("gl_account_id", sa.UUID(), nullable=True),
        sa.Column("auto_created", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["gl_account_id"], ["gl_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "buildium_gl_account_id", name="uq_buildium_gl_account_map"
        ),
    )
    op.create_index(
        "ix_buildium_gl_account_maps_organization_id",
        "buildium_gl_account_maps", ["organization_id"],
    )

    op.create_table(
        "buildium_migration_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("requested_entities", postgresql.JSONB(), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_buildium_migration_runs_organization_id", "buildium_migration_runs", ["organization_id"]
    )
    op.create_index(
        "idx_buildium_migration_runs_org", "buildium_migration_runs", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_buildium_migration_runs_org", "buildium_migration_runs")
    op.drop_index("ix_buildium_migration_runs_organization_id", "buildium_migration_runs")
    op.drop_table("buildium_migration_runs")

    op.drop_index("ix_buildium_gl_account_maps_organization_id", "buildium_gl_account_maps")
    op.drop_table("buildium_gl_account_maps")

    op.drop_index("idx_buildium_entity_maps_local", "buildium_entity_maps")
    op.drop_index("ix_buildium_entity_maps_organization_id", "buildium_entity_maps")
    op.drop_table("buildium_entity_maps")

    op.drop_index("ix_buildium_connections_organization_id", "buildium_connections")
    op.drop_table("buildium_connections")

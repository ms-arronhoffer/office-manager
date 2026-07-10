"""Add organization_id to HQ HVAC tables for tenant isolation

Revision ID: 081
Revises: 080
Create Date: 2026-07-10

The Hq* HVAC tables were created without an organization_id, making them a
shared global namespace readable/writable by every tenant. This migration adds
organization_id (nullable FK) to every top-level Hq* table and backfills
existing rows to the default organization so the newly org-scoped endpoints
keep returning them to that org (fail-closed for everyone else).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None

# Same default org seeded by migration 023.
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"

# Top-level Hq* tables (child tables hq_heat_pump_service_log and
# hq_maintenance_visits are scoped through their parent FK).
HQ_TABLES = [
    "hq_heat_pumps",
    "hq_hvac_issues",
    "hq_pm_tasks",
    "hq_pm_log",
    "hq_maintenance_contracts",
    "hq_tower_spray_log",
    "hq_backflows",
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table in HQ_TABLES:
        if not inspector.has_table(table):
            continue
        existing_cols = [c["name"] for c in inspector.get_columns(table)]
        if "organization_id" in existing_cols:
            continue
        op.add_column(table, sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_organization_id", table, "organizations",
            ["organization_id"], ["id"],
        )
        op.create_index(f"idx_{table}_organization_id", table, ["organization_id"])

    # Backfill existing rows to the default organization so they remain visible
    # to that tenant instead of being orphaned (invisible to all).
    for table in HQ_TABLES:
        if inspector.has_table(table):
            conn.execute(
                sa.text(f"UPDATE {table} SET organization_id = :org_id WHERE organization_id IS NULL"),
                {"org_id": DEFAULT_ORG_ID},
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table in reversed(HQ_TABLES):
        if not inspector.has_table(table):
            continue
        existing_cols = [c["name"] for c in inspector.get_columns(table)]
        if "organization_id" not in existing_cols:
            continue
        try:
            op.drop_index(f"idx_{table}_organization_id", table)
        except Exception:
            pass
        try:
            op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
        except Exception:
            pass
        op.drop_column(table, "organization_id")

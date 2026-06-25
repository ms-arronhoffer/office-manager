"""add soft delete columns

Revision ID: 003
Revises: 002
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

TABLES = [
    "offices",
    "leases",
    "maintenance_tickets",
    "office_transitions",
    "hvac_contracts",
    "landlords",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"))
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"idx_{table}_is_deleted", table, ["is_deleted"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"idx_{table}_is_deleted", table_name=table)
        op.drop_column(table, "deleted_at")
        op.drop_column(table, "is_deleted")

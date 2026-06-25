"""Add operating_expenses table

Revision ID: 027
Revises: 026
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operating_expenses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("lease_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("budgeted", sa.Numeric(15, 2), nullable=True),
        sa.Column("actual", sa.Numeric(15, 2), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lease_id"], ["leases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operating_expenses_organization_id", "operating_expenses", ["organization_id"])
    op.create_index("ix_operating_expenses_lease_id", "operating_expenses", ["lease_id"])
    op.create_index("ix_operating_expenses_year", "operating_expenses", ["year"])


def downgrade() -> None:
    op.drop_table("operating_expenses")

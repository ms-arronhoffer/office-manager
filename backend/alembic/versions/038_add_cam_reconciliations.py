"""Add CAM reconciliation tables (Phase 3)

Revision ID: 038
Revises: 037
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cam_reconciliations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("lease_id", sa.UUID(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("pro_rata_share", sa.Numeric(9, 6), nullable=True),
        sa.Column("rentable_sqft", sa.Numeric(12, 2), nullable=True),
        sa.Column("building_sqft", sa.Numeric(12, 2), nullable=True),
        sa.Column("gross_up_percent", sa.Numeric(5, 4), nullable=True),
        sa.Column("occupancy_percent", sa.Numeric(5, 4), nullable=True),
        sa.Column("base_year_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("expense_stop_psf", sa.Numeric(12, 4), nullable=True),
        sa.Column("cap_percent", sa.Numeric(5, 4), nullable=True),
        sa.Column("cap_type", sa.String(30), nullable=True),
        sa.Column("cap_base_year", sa.Integer(), nullable=True),
        sa.Column("cap_base_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("estimated_paid", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_pool", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("controllable_pool", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("noncontrollable_pool", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tenant_share_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("cap_applied", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("offset_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("recoverable_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("balance_due", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_id", sa.UUID(), nullable=True),
        sa.Column("journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lease_id"], ["leases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finalized_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_id", "year", name="uq_cam_recon_lease_year"),
    )
    op.create_index(
        "ix_cam_reconciliations_organization_id", "cam_reconciliations", ["organization_id"]
    )
    op.create_index("ix_cam_reconciliations_lease_id", "cam_reconciliations", ["lease_id"])

    op.create_table(
        "cam_reconciliation_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reconciliation_id", sa.UUID(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("controllable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("gross_up_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actual_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grossed_up_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"], ["cam_reconciliations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cam_reconciliation_lines_reconciliation_id",
        "cam_reconciliation_lines",
        ["reconciliation_id"],
    )


def downgrade() -> None:
    op.drop_table("cam_reconciliation_lines")
    op.drop_table("cam_reconciliations")

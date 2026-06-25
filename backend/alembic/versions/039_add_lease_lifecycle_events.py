"""Add lease lifecycle event table (Phase 4)

Revision ID: 039
Revises: 038
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lease_lifecycle_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("lease_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("pre_liability", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("pre_rou", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("new_payment_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("new_payment_frequency", sa.String(20), nullable=True),
        sa.Column("new_annual_escalation_rate", sa.Numeric(8, 6), nullable=True),
        sa.Column("new_incremental_borrowing_rate", sa.Numeric(8, 6), nullable=True),
        sa.Column("remaining_term_months", sa.Integer(), nullable=True),
        sa.Column("new_expiration", sa.Date(), nullable=True),
        sa.Column("remaining_percentage", sa.Numeric(9, 6), nullable=True),
        sa.Column("termination_penalty", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("revised_liability", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("liability_adjustment", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("rou_adjustment", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("post_liability", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("post_rou", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("gain_loss", sa.Numeric(15, 2), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lease_lifecycle_events_organization_id",
        "lease_lifecycle_events",
        ["organization_id"],
    )
    op.create_index(
        "ix_lease_lifecycle_events_lease_id",
        "lease_lifecycle_events",
        ["lease_id"],
    )


def downgrade() -> None:
    op.drop_table("lease_lifecycle_events")

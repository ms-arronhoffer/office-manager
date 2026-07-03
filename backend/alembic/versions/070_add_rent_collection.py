"""Add rent collection & payments-in (Phase 2.3)

Revision ID: 070
Revises: 069
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Link a resident to its AR billing counterparty (created lazily on billing).
    op.add_column(
        "residents",
        sa.Column("customer_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_residents_customer",
        "residents",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_residents_customer_id", "residents", ["customer_id"])

    op.create_table(
        "rent_charges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("resident_lease_id", sa.UUID(), nullable=False),
        sa.Column("charge_type", sa.String(20), nullable=False, server_default="rent"),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("day_of_month", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("late_fee_type", sa.String(10), nullable=False, server_default="none"),
        sa.Column("late_fee_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("revenue_account_code", sa.String(20), nullable=False, server_default="4000"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_billed_period", sa.Date(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["resident_lease_id"], ["resident_leases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rent_charges_organization_id", "rent_charges", ["organization_id"])
    op.create_index("idx_rent_charges_lease", "rent_charges", ["resident_lease_id"])
    op.create_index("idx_rent_charges_active", "rent_charges", ["active"])

    op.create_table(
        "security_deposits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("resident_lease_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("held_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="held"),
        sa.Column("returned_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("forfeited_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("returned_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("return_journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["resident_lease_id"], ["resident_leases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["return_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_deposits_organization_id", "security_deposits", ["organization_id"])
    op.create_index("idx_security_deposits_lease", "security_deposits", ["resident_lease_id"])
    op.create_index("idx_security_deposits_status", "security_deposits", ["status"])


def downgrade() -> None:
    op.drop_table("security_deposits")
    op.drop_table("rent_charges")
    op.drop_index("ix_residents_customer_id", table_name="residents")
    op.drop_constraint("fk_residents_customer", "residents", type_="foreignkey")
    op.drop_column("residents", "customer_id")

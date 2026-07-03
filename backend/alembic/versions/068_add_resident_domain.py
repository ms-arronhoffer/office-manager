"""Add tenant/resident domain (Phase 2.1 — org-as-lessor leasing)

Revision ID: 068
Revises: 067
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rental_units",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("office_id", sa.UUID(), nullable=True),
        sa.Column("unit_number", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("floor", sa.String(20), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Numeric(4, 1), nullable=True),
        sa.Column("square_feet", sa.Numeric(12, 2), nullable=True),
        sa.Column("market_rent", sa.Numeric(15, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("office_id", "unit_number", name="uq_rental_unit_office_number"),
    )
    op.create_index("ix_rental_units_organization_id", "rental_units", ["organization_id"])
    op.create_index("idx_rental_units_office", "rental_units", ["office_id"])
    op.create_index("idx_rental_units_status", "rental_units", ["status"])

    op.create_table(
        "residents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("emergency_contact_name", sa.String(255), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="prospect"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_residents_organization_id", "residents", ["organization_id"])
    op.create_index("idx_residents_status", "residents", ["status"])
    op.create_index("idx_residents_last_name", "residents", ["last_name"])

    op.create_table(
        "resident_leases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("unit_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("move_in_date", sa.Date(), nullable=True),
        sa.Column("move_out_date", sa.Date(), nullable=True),
        sa.Column("rent_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("rent_frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("rent_due_day", sa.Integer(), nullable=True),
        sa.Column("security_deposit", sa.Numeric(15, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["rental_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resident_leases_organization_id", "resident_leases", ["organization_id"])
    op.create_index("idx_resident_leases_unit", "resident_leases", ["unit_id"])
    op.create_index("idx_resident_leases_status", "resident_leases", ["status"])
    op.create_index("idx_resident_leases_end_date", "resident_leases", ["end_date"])

    op.create_table(
        "resident_lease_occupants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lease_id", sa.UUID(), nullable=False),
        sa.Column("resident_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="primary"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lease_id"], ["resident_leases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resident_id"], ["residents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_id", "resident_id", name="uq_resident_lease_occupant"),
    )
    op.create_index(
        "idx_resident_lease_occupants_lease", "resident_lease_occupants", ["lease_id"]
    )
    op.create_index(
        "idx_resident_lease_occupants_resident", "resident_lease_occupants", ["resident_id"]
    )


def downgrade() -> None:
    op.drop_table("resident_lease_occupants")
    op.drop_table("resident_leases")
    op.drop_table("residents")
    op.drop_table("rental_units")

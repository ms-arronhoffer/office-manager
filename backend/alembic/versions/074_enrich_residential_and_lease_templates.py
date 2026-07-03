"""Enrich residential fields and add custom lease templates

Adds Portfolio-parity detail columns to the residential domain
(``rental_units``, ``residents``, ``resident_leases``) and a new
``lease_templates`` table backing custom, reusable lease documents that drive the
resident-lease e-signing engine.

Revision ID: 074
Revises: 073
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── rental_units: address & marketing detail ─────────────────────────────
    op.add_column("rental_units", sa.Column("address_line_1", sa.String(255), nullable=True))
    op.add_column("rental_units", sa.Column("address_line_2", sa.String(255), nullable=True))
    op.add_column("rental_units", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("rental_units", sa.Column("state", sa.String(2), nullable=True))
    op.add_column("rental_units", sa.Column("zip_code", sa.String(10), nullable=True))
    op.add_column("rental_units", sa.Column("property_type", sa.String(50), nullable=True))
    op.add_column("rental_units", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("rental_units", sa.Column("amenities", sa.Text(), nullable=True))
    op.add_column("rental_units", sa.Column("year_built", sa.Integer(), nullable=True))
    op.add_column("rental_units", sa.Column("available_date", sa.Date(), nullable=True))

    # ── residents: contact & mailing address detail ──────────────────────────
    op.add_column("residents", sa.Column("alternate_phone", sa.String(50), nullable=True))
    op.add_column("residents", sa.Column("company", sa.String(255), nullable=True))
    op.add_column("residents", sa.Column("address_line_1", sa.String(255), nullable=True))
    op.add_column("residents", sa.Column("address_line_2", sa.String(255), nullable=True))
    op.add_column("residents", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("residents", sa.Column("state", sa.String(2), nullable=True))
    op.add_column("residents", sa.Column("zip_code", sa.String(10), nullable=True))

    # ── resident_leases: richer lease terms ──────────────────────────────────
    op.add_column("resident_leases", sa.Column("lease_type", sa.String(20), nullable=True))
    op.add_column("resident_leases", sa.Column("rent_escalation_rate", sa.Numeric(8, 6), nullable=True))
    op.add_column("resident_leases", sa.Column("late_fee_amount", sa.Numeric(15, 2), nullable=True))
    op.add_column("resident_leases", sa.Column("late_fee_grace_days", sa.Integer(), nullable=True))
    op.add_column("resident_leases", sa.Column("notice_period_days", sa.Integer(), nullable=True))
    op.add_column("resident_leases", sa.Column("pet_deposit", sa.Numeric(15, 2), nullable=True))
    op.add_column(
        "resident_leases",
        sa.Column("renewal_option", sa.Boolean(), nullable=False, server_default="false"),
    )

    # ── lease_templates: custom reusable lease documents ─────────────────────
    op.create_table(
        "lease_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lease_templates_organization_id", "lease_templates", ["organization_id"])
    op.create_index("idx_lease_templates_org", "lease_templates", ["organization_id"])
    op.create_index("idx_lease_templates_active", "lease_templates", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_lease_templates_active", table_name="lease_templates")
    op.drop_index("idx_lease_templates_org", table_name="lease_templates")
    op.drop_index("ix_lease_templates_organization_id", table_name="lease_templates")
    op.drop_table("lease_templates")

    for col in (
        "renewal_option",
        "pet_deposit",
        "notice_period_days",
        "late_fee_grace_days",
        "late_fee_amount",
        "rent_escalation_rate",
        "lease_type",
    ):
        op.drop_column("resident_leases", col)

    for col in (
        "zip_code",
        "state",
        "city",
        "address_line_2",
        "address_line_1",
        "company",
        "alternate_phone",
    ):
        op.drop_column("residents", col)

    for col in (
        "available_date",
        "year_built",
        "amenities",
        "description",
        "property_type",
        "zip_code",
        "state",
        "city",
        "address_line_2",
        "address_line_1",
    ):
        op.drop_column("rental_units", col)

"""Add primary categories to orgs + self-storage domain tables

Adds:
* ``organizations.enabled_categories`` (JSONB, org-managed primary categories,
  default ``["commercial", "residential"]``) and
  ``organizations.category_overrides`` (JSONB, platform super-admin overrides).
* The self-storage domain tables: ``storage_units``, ``storage_agreements``,
  ``storage_agreement_occupants``, ``storage_reservations``,
  ``storage_rate_plans``, ``storage_lien_events``, ``storage_charges``.

Self storage reuses ``offices`` as the facility and ``residents`` as the tenant,
so those FKs point at existing tables.

Idempotent: guards on column/table existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 099
Revises: 098
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- Organization primary-category columns ------------------------------
    if not _has_column(inspector, "organizations", "enabled_categories"):
        op.add_column(
            "organizations",
            sa.Column(
                "enabled_categories",
                JSONB(),
                nullable=False,
                server_default='["commercial", "residential"]',
            ),
        )
    if not _has_column(inspector, "organizations", "category_overrides"):
        op.add_column(
            "organizations",
            sa.Column(
                "category_overrides",
                JSONB(),
                nullable=False,
                server_default="{}",
            ),
        )

    tables = set(inspector.get_table_names())

    # --- storage_units ------------------------------------------------------
    if "storage_units" not in tables:
        op.create_table(
            "storage_units",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=True),
            sa.Column("office_id", sa.UUID(), nullable=True),
            sa.Column("unit_number", sa.String(50), nullable=False),
            sa.Column("building", sa.String(50), nullable=True),
            sa.Column("row", sa.String(50), nullable=True),
            sa.Column("floor", sa.String(20), nullable=True),
            sa.Column("width_ft", sa.Numeric(8, 2), nullable=True),
            sa.Column("length_ft", sa.Numeric(8, 2), nullable=True),
            sa.Column("height_ft", sa.Numeric(8, 2), nullable=True),
            sa.Column("square_feet", sa.Numeric(12, 2), nullable=True),
            sa.Column("cubic_feet", sa.Numeric(12, 2), nullable=True),
            sa.Column("size_label", sa.String(50), nullable=True),
            sa.Column("size_tier", sa.String(50), nullable=True),
            sa.Column("unit_type", sa.String(20), nullable=False, server_default="interior"),
            sa.Column("climate_controlled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("has_power", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("is_alarmed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("drive_up_access", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("ground_floor", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("elevator_access", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("access_24hr", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("street_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("standard_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("in_place_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("promo_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("status", sa.String(20), nullable=False, server_default="available"),
            sa.Column("lock_state", sa.String(20), nullable=False, server_default="unlocked"),
            sa.Column("gate_zone", sa.String(50), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("office_id", "unit_number", name="uq_storage_unit_office_number"),
        )
        op.create_index("idx_storage_units_office", "storage_units", ["office_id"])
        op.create_index("idx_storage_units_status", "storage_units", ["status"])
        op.create_index("idx_storage_units_size_tier", "storage_units", ["size_tier"])
        op.create_index("ix_storage_units_organization_id", "storage_units", ["organization_id"])

    # --- storage_agreements -------------------------------------------------
    if "storage_agreements" not in tables:
        op.create_table(
            "storage_agreements",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=True),
            sa.Column("unit_id", sa.UUID(), nullable=False),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("rent_amount", sa.Numeric(15, 2), nullable=True),
            sa.Column("security_deposit", sa.Numeric(15, 2), nullable=True),
            sa.Column("admin_fee", sa.Numeric(15, 2), nullable=True),
            sa.Column("billing_day", sa.Integer(), nullable=True),
            sa.Column("billing_cycle", sa.String(20), nullable=False, server_default="monthly"),
            sa.Column("autopay_enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("autopay_method", sa.String(20), nullable=True),
            sa.Column("insurance_plan", sa.String(100), nullable=True),
            sa.Column("insurance_coverage", sa.Numeric(15, 2), nullable=True),
            sa.Column("insurance_premium", sa.Numeric(15, 2), nullable=True),
            sa.Column("gate_code", sa.String(20), nullable=True),
            sa.Column("late_fee_amount", sa.Numeric(15, 2), nullable=True),
            sa.Column("late_fee_grace_days", sa.Integer(), nullable=True),
            sa.Column("move_in_date", sa.Date(), nullable=True),
            sa.Column("move_out_date", sa.Date(), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["unit_id"], ["storage_units.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_storage_agreements_unit", "storage_agreements", ["unit_id"])
        op.create_index("idx_storage_agreements_status", "storage_agreements", ["status"])
        op.create_index("idx_storage_agreements_move_out", "storage_agreements", ["move_out_date"])
        op.create_index("ix_storage_agreements_organization_id", "storage_agreements", ["organization_id"])

    # --- storage_agreement_occupants ---------------------------------------
    if "storage_agreement_occupants" not in tables:
        op.create_table(
            "storage_agreement_occupants",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("agreement_id", sa.UUID(), nullable=False),
            sa.Column("resident_id", sa.UUID(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="primary"),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["agreement_id"], ["storage_agreements.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["resident_id"], ["residents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agreement_id", "resident_id", name="uq_storage_agreement_occupant"),
        )
        op.create_index("idx_storage_agreement_occupants_agreement", "storage_agreement_occupants", ["agreement_id"])
        op.create_index("idx_storage_agreement_occupants_resident", "storage_agreement_occupants", ["resident_id"])

    # --- storage_reservations ----------------------------------------------
    if "storage_reservations" not in tables:
        op.create_table(
            "storage_reservations",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=True),
            sa.Column("office_id", sa.UUID(), nullable=True),
            sa.Column("unit_id", sa.UUID(), nullable=True),
            sa.Column("resident_id", sa.UUID(), nullable=True),
            sa.Column("prospect_name", sa.String(255), nullable=True),
            sa.Column("prospect_email", sa.String(255), nullable=True),
            sa.Column("prospect_phone", sa.String(50), nullable=True),
            sa.Column("size_tier", sa.String(50), nullable=True),
            sa.Column("quoted_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="held"),
            sa.Column("hold_until", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
            sa.ForeignKeyConstraint(["unit_id"], ["storage_units.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resident_id"], ["residents.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_storage_reservations_status", "storage_reservations", ["status"])
        op.create_index("idx_storage_reservations_unit", "storage_reservations", ["unit_id"])
        op.create_index("ix_storage_reservations_organization_id", "storage_reservations", ["organization_id"])

    # --- storage_rate_plans -------------------------------------------------
    if "storage_rate_plans" not in tables:
        op.create_table(
            "storage_rate_plans",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=True),
            sa.Column("office_id", sa.UUID(), nullable=True),
            sa.Column("size_tier", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("street_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("standard_rate", sa.Numeric(15, 2), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("increase_effective_date", sa.Date(), nullable=True),
            sa.Column("increase_amount", sa.Numeric(15, 2), nullable=True),
            sa.Column("increase_percent", sa.Numeric(8, 4), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["office_id"], ["offices.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_storage_rate_plans_office", "storage_rate_plans", ["office_id"])
        op.create_index("idx_storage_rate_plans_size_tier", "storage_rate_plans", ["size_tier"])
        op.create_index("ix_storage_rate_plans_organization_id", "storage_rate_plans", ["organization_id"])

    # --- storage_lien_events -----------------------------------------------
    if "storage_lien_events" not in tables:
        op.create_table(
            "storage_lien_events",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=True),
            sa.Column("agreement_id", sa.UUID(), nullable=False),
            sa.Column("step", sa.String(30), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("amount_due", sa.Numeric(15, 2), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_id", sa.UUID(), nullable=True),
            sa.Column("details", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["agreement_id"], ["storage_agreements.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_storage_lien_events_agreement", "storage_lien_events", ["agreement_id"])
        op.create_index("idx_storage_lien_events_step", "storage_lien_events", ["step"])
        op.create_index("ix_storage_lien_events_organization_id", "storage_lien_events", ["organization_id"])

    # --- storage_charges ----------------------------------------------------
    if "storage_charges" not in tables:
        op.create_table(
            "storage_charges",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=True),
            sa.Column("storage_agreement_id", sa.UUID(), nullable=False),
            sa.Column("charge_type", sa.String(20), nullable=False, server_default="rent"),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("amount", sa.Numeric(15, 2), nullable=False),
            sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
            sa.Column("day_of_month", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("grace_days", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("late_fee_type", sa.String(20), nullable=False, server_default="none"),
            sa.Column("late_fee_amount", sa.Numeric(15, 2), nullable=True),
            sa.Column("revenue_account_code", sa.String(20), nullable=False, server_default="4100"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("last_billed_period", sa.Date(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["storage_agreement_id"], ["storage_agreements.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_storage_charges_agreement", "storage_charges", ["storage_agreement_id"])
        op.create_index("idx_storage_charges_active", "storage_charges", ["active"])
        op.create_index("ix_storage_charges_organization_id", "storage_charges", ["organization_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table in (
        "storage_charges",
        "storage_lien_events",
        "storage_rate_plans",
        "storage_reservations",
        "storage_agreement_occupants",
        "storage_agreements",
        "storage_units",
    ):
        if table in tables:
            op.drop_table(table)
    if _has_column(inspector, "organizations", "category_overrides"):
        op.drop_column("organizations", "category_overrides")
    if _has_column(inspector, "organizations", "enabled_categories"):
        op.drop_column("organizations", "enabled_categories")

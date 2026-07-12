"""Give self storage its own Property (facility) data set

Self storage previously reused ``offices`` (the commercial Property) as its
facility. This makes the self-storage *property* its own data set so the
category stands on its own even when Commercial is turned off:

* Adds the ``storage_facilities`` table.
* Repoints ``storage_units``, ``storage_reservations``, and
  ``storage_rate_plans`` from ``office_id`` (FK ``offices``) to ``facility_id``
  (FK ``storage_facilities``).

Idempotent: guards on table/column/index/constraint existence so create_all+stamp
fresh DBs (which already have ``facility_id`` and no ``office_id``) and DBs
migrated at revision 099 (which still have ``office_id``) both apply cleanly.

Revision ID: 100
Revises: 099
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa


revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return index in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_unique(inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {uc["name"] for uc in inspector.get_unique_constraints(table)}


def _create_facilities(inspector) -> None:
    if _has_table(inspector, "storage_facilities"):
        return
    op.create_table(
        "storage_facilities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("facility_number", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("address_line_1", sa.String(255), nullable=True),
        sa.Column("address_line_2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("zip_code", sa.String(10), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("manager_name", sa.String(255), nullable=True),
        sa.Column("gate_hours", sa.String(255), nullable=True),
        sa.Column("access_hours", sa.String(255), nullable=True),
        sa.Column("total_units", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_storage_facilities_org", "storage_facilities", ["organization_id"])
    op.create_index("idx_storage_facilities_active", "storage_facilities", ["is_active"])
    op.create_index("ix_storage_facilities_organization_id", "storage_facilities", ["organization_id"])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _create_facilities(inspector)
    inspector = sa.inspect(bind)

    # --- storage_units: office_id -> facility_id ----------------------------
    if _has_table(inspector, "storage_units"):
        if not _has_column(inspector, "storage_units", "facility_id"):
            op.add_column("storage_units", sa.Column("facility_id", sa.UUID(), nullable=True))
            op.create_foreign_key(
                "fk_storage_units_facility_id", "storage_units",
                "storage_facilities", ["facility_id"], ["id"],
            )
            op.create_index("idx_storage_units_facility", "storage_units", ["facility_id"])
            op.create_index("ix_storage_units_facility_id", "storage_units", ["facility_id"])
        if not _has_unique(inspector, "storage_units", "uq_storage_unit_facility_number"):
            op.create_unique_constraint(
                "uq_storage_unit_facility_number", "storage_units",
                ["facility_id", "unit_number"],
            )
        # Dropping office_id cascades its FK, index, and unique constraint in
        # Postgres; drop the named artefacts first where present to be explicit.
        if _has_index(inspector, "storage_units", "idx_storage_units_office"):
            op.drop_index("idx_storage_units_office", table_name="storage_units")
        if _has_unique(inspector, "storage_units", "uq_storage_unit_office_number"):
            op.drop_constraint("uq_storage_unit_office_number", "storage_units", type_="unique")
        if _has_column(inspector, "storage_units", "office_id"):
            op.drop_column("storage_units", "office_id")

    # --- storage_agreements: add direct facility link (like Lease.office) ---
    if _has_table(inspector, "storage_agreements"):
        if not _has_column(inspector, "storage_agreements", "facility_id"):
            op.add_column("storage_agreements", sa.Column("facility_id", sa.UUID(), nullable=True))
            op.create_foreign_key(
                "fk_storage_agreements_facility_id", "storage_agreements",
                "storage_facilities", ["facility_id"], ["id"],
            )
            op.create_index("idx_storage_agreements_facility", "storage_agreements", ["facility_id"])
            op.create_index("ix_storage_agreements_facility_id", "storage_agreements", ["facility_id"])

    # --- storage_reservations: office_id -> facility_id ---------------------
    if _has_table(inspector, "storage_reservations"):
        if not _has_column(inspector, "storage_reservations", "facility_id"):
            op.add_column("storage_reservations", sa.Column("facility_id", sa.UUID(), nullable=True))
            op.create_foreign_key(
                "fk_storage_reservations_facility_id", "storage_reservations",
                "storage_facilities", ["facility_id"], ["id"],
            )
            op.create_index("ix_storage_reservations_facility_id", "storage_reservations", ["facility_id"])
        if _has_column(inspector, "storage_reservations", "office_id"):
            op.drop_column("storage_reservations", "office_id")

    # --- storage_rate_plans: office_id -> facility_id -----------------------
    if _has_table(inspector, "storage_rate_plans"):
        if not _has_column(inspector, "storage_rate_plans", "facility_id"):
            op.add_column("storage_rate_plans", sa.Column("facility_id", sa.UUID(), nullable=True))
            op.create_foreign_key(
                "fk_storage_rate_plans_facility_id", "storage_rate_plans",
                "storage_facilities", ["facility_id"], ["id"],
            )
            op.create_index("idx_storage_rate_plans_facility", "storage_rate_plans", ["facility_id"])
        if _has_index(inspector, "storage_rate_plans", "idx_storage_rate_plans_office"):
            op.drop_index("idx_storage_rate_plans_office", table_name="storage_rate_plans")
        if _has_column(inspector, "storage_rate_plans", "office_id"):
            op.drop_column("storage_rate_plans", "office_id")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Restore office_id columns (nullable, no data migration back).
    if _has_table(inspector, "storage_rate_plans"):
        if not _has_column(inspector, "storage_rate_plans", "office_id"):
            op.add_column("storage_rate_plans", sa.Column("office_id", sa.UUID(), nullable=True))
            op.create_foreign_key(None, "storage_rate_plans", "offices", ["office_id"], ["id"])
            op.create_index("idx_storage_rate_plans_office", "storage_rate_plans", ["office_id"])
        if _has_index(inspector, "storage_rate_plans", "idx_storage_rate_plans_facility"):
            op.drop_index("idx_storage_rate_plans_facility", table_name="storage_rate_plans")
        if _has_column(inspector, "storage_rate_plans", "facility_id"):
            op.drop_column("storage_rate_plans", "facility_id")

    if _has_table(inspector, "storage_reservations"):
        if not _has_column(inspector, "storage_reservations", "office_id"):
            op.add_column("storage_reservations", sa.Column("office_id", sa.UUID(), nullable=True))
            op.create_foreign_key(None, "storage_reservations", "offices", ["office_id"], ["id"])
        if _has_column(inspector, "storage_reservations", "facility_id"):
            op.drop_column("storage_reservations", "facility_id")

    if _has_table(inspector, "storage_units"):
        if not _has_column(inspector, "storage_units", "office_id"):
            op.add_column("storage_units", sa.Column("office_id", sa.UUID(), nullable=True))
            op.create_foreign_key(None, "storage_units", "offices", ["office_id"], ["id"])
            op.create_index("idx_storage_units_office", "storage_units", ["office_id"])
            op.create_unique_constraint(
                "uq_storage_unit_office_number", "storage_units", ["office_id", "unit_number"]
            )
        if _has_unique(inspector, "storage_units", "uq_storage_unit_facility_number"):
            op.drop_constraint("uq_storage_unit_facility_number", "storage_units", type_="unique")
        if _has_index(inspector, "storage_units", "idx_storage_units_facility"):
            op.drop_index("idx_storage_units_facility", table_name="storage_units")
        if _has_column(inspector, "storage_units", "facility_id"):
            op.drop_column("storage_units", "facility_id")

    if _has_table(inspector, "storage_agreements"):
        if _has_index(inspector, "storage_agreements", "idx_storage_agreements_facility"):
            op.drop_index("idx_storage_agreements_facility", table_name="storage_agreements")
        if _has_column(inspector, "storage_agreements", "facility_id"):
            op.drop_column("storage_agreements", "facility_id")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "storage_facilities"):
        op.drop_table("storage_facilities")

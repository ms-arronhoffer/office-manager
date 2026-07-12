"""Give self storage its own Manager data set

Self storage previously stored the facility manager only as a free-text
``manager_name`` field. This makes the self-storage *manager* a first-class data
set (mirroring the commercial ``managers`` table / ``Office.manager_id``), kept
separate so the category stands on its own even when Commercial is turned off:

* Adds the ``storage_managers`` table.
* Adds ``storage_facilities.manager_id`` (FK ``storage_managers``).

The legacy ``manager_name`` column is retained for backward compatibility.

Idempotent: guards on table/column/index/constraint existence so create_all+stamp
fresh DBs (which already have the table/column) and DBs migrated at revision 100
(which do not) both apply cleanly.

Revision ID: 101
Revises: 100
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa


revision = "101"
down_revision = "100"
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


def _create_managers(inspector) -> None:
    if _has_table(inspector, "storage_managers"):
        return
    op.create_table(
        "storage_managers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_storage_manager_org_name"
        ),
    )
    op.create_index("idx_storage_managers_org", "storage_managers", ["organization_id"])
    op.create_index(
        "ix_storage_managers_organization_id", "storage_managers", ["organization_id"]
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _create_managers(inspector)
    inspector = sa.inspect(bind)

    if _has_table(inspector, "storage_facilities"):
        if not _has_column(inspector, "storage_facilities", "manager_id"):
            op.add_column(
                "storage_facilities", sa.Column("manager_id", sa.UUID(), nullable=True)
            )
            op.create_foreign_key(
                "fk_storage_facilities_manager_id", "storage_facilities",
                "storage_managers", ["manager_id"], ["id"],
            )
        if not _has_index(inspector, "storage_facilities", "idx_storage_facilities_manager"):
            op.create_index(
                "idx_storage_facilities_manager", "storage_facilities", ["manager_id"]
            )
        if not _has_index(inspector, "storage_facilities", "ix_storage_facilities_manager_id"):
            op.create_index(
                "ix_storage_facilities_manager_id", "storage_facilities", ["manager_id"]
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "storage_facilities"):
        if _has_index(inspector, "storage_facilities", "ix_storage_facilities_manager_id"):
            op.drop_index("ix_storage_facilities_manager_id", table_name="storage_facilities")
        if _has_index(inspector, "storage_facilities", "idx_storage_facilities_manager"):
            op.drop_index("idx_storage_facilities_manager", table_name="storage_facilities")
        if _has_column(inspector, "storage_facilities", "manager_id"):
            op.drop_column("storage_facilities", "manager_id")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "storage_managers"):
        op.drop_table("storage_managers")

"""Scope commercial manager name uniqueness to the organization

``managers.name`` historically carried a *global* unique constraint
(``managers_name_key``). In a multi-tenant deployment this made two
organizations unable to have a manager with the same name, and any duplicate
insert raised a raw ``IntegrityError`` that surfaced to the UI as a generic
"Failed to create manager" 500 (even though the offending row was never
created). This mirrors the self-storage ``StorageManager`` model, which already
uses a per-organization unique constraint.

This migration drops the global unique constraint/index and adds a composite
``(organization_id, name)`` unique constraint.

Idempotent: guards on constraint/index existence so a create_all+stamp fresh DB
(which already has ``uq_managers_org_name`` and never had ``managers_name_key``)
and a long-lived DB (which has the old global constraint) both apply cleanly.

Revision ID: 105
Revises: 104
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa


revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None

TABLE = "managers"
GLOBAL_CONSTRAINT = "managers_name_key"
COMPOSITE_CONSTRAINT = "uq_managers_org_name"


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _unique_constraints(inspector, table: str) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    names = {uc["name"] for uc in inspector.get_unique_constraints(table)}
    # A column-level ``unique=True`` can also be reported as an index.
    names |= {ix["name"] for ix in inspector.get_indexes(table) if ix.get("unique")}
    return {n for n in names if n}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, TABLE):
        return

    existing = _unique_constraints(inspector, TABLE)

    if GLOBAL_CONSTRAINT in existing:
        # Postgres backs a unique constraint with an index of the same name;
        # dropping the constraint removes both. ``IF EXISTS`` keeps it safe.
        op.execute(
            f'ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS "{GLOBAL_CONSTRAINT}"'
        )

    if COMPOSITE_CONSTRAINT not in existing:
        op.create_unique_constraint(
            COMPOSITE_CONSTRAINT, TABLE, ["organization_id", "name"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, TABLE):
        return

    existing = _unique_constraints(inspector, TABLE)

    if COMPOSITE_CONSTRAINT in existing:
        op.drop_constraint(COMPOSITE_CONSTRAINT, TABLE, type_="unique")

    if GLOBAL_CONSTRAINT not in existing:
        op.create_unique_constraint(GLOBAL_CONSTRAINT, TABLE, ["name"])

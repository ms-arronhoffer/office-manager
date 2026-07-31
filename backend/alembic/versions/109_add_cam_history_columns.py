"""Add historical-period, financial and provenance columns to the CAM schedule

An organization onboarding an existing tenancy often has years of prior leases,
amendments and reconciliation statements. Those prior years are imported into
``lease_cam_entries`` as reference rows so the *active* lease record stays the
single source of truth for the current financial terms.

Adds to ``lease_cam_entries``:

* period/scope — ``period_start``, ``period_end``, ``period_status``
  (``historical`` | ``current`` | ``projected``, defaulting to ``current`` so
  every pre-existing row remains part of the active schedule).
* financial breadth — ``base_rent_amount``, ``base_rent_frequency``,
  ``base_rent_escalation_rate``, ``operating_expense_amount``, ``cam_psf``,
  ``reconciliation_true_up``.
* provenance — ``source``, ``source_document_id``, ``import_batch_id``,
  ``extraction_confidence``, ``review_status``, ``imported_at``.

Rows are deduplicated by (lease_id, year, period_status) in the import service
rather than by a database unique constraint: existing databases may already
hold several rows for one lease-year, and a unique index would make this
migration fail on them.

Idempotent: guards on table/column existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 109
Revises: 108
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None

TABLE = "lease_cam_entries"


def _new_columns() -> list[sa.Column]:
    """Fresh Column objects (a Column may only be bound to one Table)."""
    return [
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column(
            "period_status",
            sa.String(length=20),
            nullable=False,
            server_default="current",
        ),
        sa.Column("base_rent_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("base_rent_frequency", sa.String(length=20), nullable=True),
        sa.Column("base_rent_escalation_rate", sa.Numeric(8, 6), nullable=True),
        sa.Column("operating_expense_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("cam_psf", sa.Numeric(12, 4), nullable=True),
        sa.Column("reconciliation_true_up", sa.Numeric(15, 2), nullable=True),
        sa.Column(
            "source", sa.String(length=20), nullable=False, server_default="manual"
        ),
        sa.Column(
            "source_document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("import_batch_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("extraction_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="accepted",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
    ]


NEW_INDEXES = (
    ("idx_lease_cam_entries_lease_year", ["lease_id", "year"]),
    ("idx_lease_cam_entries_batch", ["import_batch_id"]),
)


def _columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns(TABLE)}


def _indexes(inspector) -> set[str]:
    return {i["name"] for i in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return

    existing = _columns(inspector)
    for column in _new_columns():
        if column.name not in existing:
            op.add_column(TABLE, column)

    existing_indexes = _indexes(inspector)
    for name, columns in NEW_INDEXES:
        if name not in existing_indexes:
            op.create_index(name, TABLE, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return

    existing_indexes = _indexes(inspector)
    for name, _columns_ in NEW_INDEXES:
        if name in existing_indexes:
            op.drop_index(name, table_name=TABLE)

    existing = _columns(inspector)
    for column in reversed(_new_columns()):
        if column.name in existing:
            op.drop_column(TABLE, column.name)

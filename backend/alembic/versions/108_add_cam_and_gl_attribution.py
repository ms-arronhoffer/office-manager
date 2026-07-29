"""Add CAM schedule table and GL-account attribution columns

Adds a per-year CAM (common-area-maintenance) schedule for leases and lets
expenses be attributed to a chart-of-accounts (GL) entry:

* ``lease_cam_entries`` — one row per lease-year with a charge type (fixed
  amount or percent increase over the prior year), value, optional GL account,
  and notes.
* ``offices.gl_account_id`` — GL account an office's activity is attributed to.
* ``vendors.default_gl_account_id`` — default expense account for a vendor.
* ``maintenance_logs.gl_account_id`` — GL account a maintenance expense hits.
* ``operating_expenses.gl_account_id`` — GL account an operating expense hits.

Idempotent: guards on table/column existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 108
Revises: 107
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _add_gl_column(inspector, table: str, column: str) -> None:
    """Add a nullable GL-account FK column to ``table`` if it is missing."""
    if table not in inspector.get_table_names():
        return
    if column in _columns(inspector, table):
        return
    op.add_column(
        table,
        sa.Column(
            column,
            sa.UUID(as_uuid=True),
            sa.ForeignKey("gl_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "lease_cam_entries" not in inspector.get_table_names():
        op.create_table(
            "lease_cam_entries",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=True,
            ),
            sa.Column(
                "lease_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("leases.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column(
                "charge_type",
                sa.String(length=20),
                nullable=False,
                server_default="fixed",
            ),
            sa.Column("amount", sa.Numeric(15, 2), nullable=True),
            sa.Column("percent_increase", sa.Numeric(8, 6), nullable=True),
            sa.Column(
                "gl_account_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("gl_accounts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.String(length=1000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "idx_lease_cam_entries_lease", "lease_cam_entries", ["lease_id"]
        )
        op.create_index(
            "idx_lease_cam_entries_gl", "lease_cam_entries", ["gl_account_id"]
        )
        op.create_index(
            "ix_lease_cam_entries_organization_id",
            "lease_cam_entries",
            ["organization_id"],
        )

    _add_gl_column(inspector, "offices", "gl_account_id")
    _add_gl_column(inspector, "vendors", "default_gl_account_id")
    _add_gl_column(inspector, "maintenance_logs", "gl_account_id")
    _add_gl_column(inspector, "operating_expenses", "gl_account_id")


def _drop_gl_column(inspector, table: str, column: str) -> None:
    if table not in inspector.get_table_names():
        return
    if column in _columns(inspector, table):
        op.drop_column(table, column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _drop_gl_column(inspector, "operating_expenses", "gl_account_id")
    _drop_gl_column(inspector, "maintenance_logs", "gl_account_id")
    _drop_gl_column(inspector, "vendors", "default_gl_account_id")
    _drop_gl_column(inspector, "offices", "gl_account_id")

    if "lease_cam_entries" in inspector.get_table_names():
        op.drop_table("lease_cam_entries")

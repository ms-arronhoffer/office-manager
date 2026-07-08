"""Replace lease Quarem fields with a lease lifecycle status

Drops the ``quarem_date`` column entirely and renames ``quarem_status`` to
``status`` on the ``leases`` table. ``status`` now holds a lease lifecycle
status code (e.g. ``active``, ``pending``, ``expired``) surfaced as a drop-down
in the UI and a filterable column on the Leases table.

Revision ID: 077
Revises: 076
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("leases", "quarem_date")
    op.alter_column(
        "leases",
        "quarem_status",
        new_column_name="status",
        existing_type=sa.Text(),
        type_=sa.String(length=50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "leases",
        "status",
        new_column_name="quarem_status",
        existing_type=sa.String(length=50),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.add_column(
        "leases",
        sa.Column("quarem_date", sa.Date(), nullable=True),
    )

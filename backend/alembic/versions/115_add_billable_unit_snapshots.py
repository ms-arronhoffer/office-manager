"""Add billable unit snapshots for per-unit (banded) billing.

Revision ID: 115
Revises: 114
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None

_SNAPSHOTS = "billable_unit_snapshots"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _SNAPSHOTS in inspector.get_table_names():
        return

    op.create_table(
        _SNAPSHOTS,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Billing period the snapshot describes, "YYYY-MM".
        sa.Column("period_month", sa.String(7), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("billable_units", sa.Integer(), nullable=False, server_default="0"),
        # Per-category counts that sum to billable_units.
        sa.Column("breakdown", JSONB, nullable=True),
        sa.UniqueConstraint(
            "organization_id", "period_month", name="uq_billable_unit_snapshot_org_period"
        ),
    )
    op.create_index("idx_billable_unit_snapshots_org", _SNAPSHOTS, ["organization_id"])
    op.create_index("idx_billable_unit_snapshots_period", _SNAPSHOTS, ["period_month"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _SNAPSHOTS not in inspector.get_table_names():
        return
    op.drop_index("idx_billable_unit_snapshots_period", table_name=_SNAPSHOTS)
    op.drop_index("idx_billable_unit_snapshots_org", table_name=_SNAPSHOTS)
    op.drop_table(_SNAPSHOTS)

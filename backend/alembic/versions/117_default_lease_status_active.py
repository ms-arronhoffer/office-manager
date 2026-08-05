"""Default unset commercial and residential lease statuses to active.

Revision ID: 117
Revises: 116
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize historical unset values first so every existing lease has an
    # explicit lifecycle state and is represented in this month's billing
    # ledger. The usage-table uniqueness constraint makes the backfill safe to
    # rerun and preserves rows already written by revision 116.
    op.execute("UPDATE leases SET status = 'active' WHERE status IS NULL OR btrim(status) = ''")
    op.execute(
        "UPDATE resident_leases SET status = 'active' "
        "WHERE status IS NULL OR btrim(status) = ''"
    )
    op.alter_column(
        "leases",
        "status",
        existing_type=sa.String(length=50),
        server_default="active",
        existing_nullable=True,
    )
    op.alter_column(
        "resident_leases",
        "status",
        existing_type=sa.String(length=20),
        server_default="active",
        existing_nullable=False,
    )
    op.execute(
        """
        INSERT INTO active_lease_months
            (id, organization_id, lease_type, lease_id, period_month, first_active_at)
        SELECT gen_random_uuid(), organization_id, 'commercial', id,
               to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM'), now()
        FROM leases
        WHERE organization_id IS NOT NULL
          AND is_deleted = false
          AND lower(btrim(status)) = 'active'
        ON CONFLICT ON CONSTRAINT uq_active_lease_month_org_lease_period DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO active_lease_months
            (id, organization_id, lease_type, lease_id, period_month, first_active_at)
        SELECT gen_random_uuid(), organization_id, 'residential', id,
               to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM'), now()
        FROM resident_leases
        WHERE organization_id IS NOT NULL
          AND is_deleted = false
          AND lower(btrim(status)) = 'active'
        ON CONFLICT ON CONSTRAINT uq_active_lease_month_org_lease_period DO NOTHING
        """
    )


def downgrade() -> None:
    # Preserve explicit active values; only restore the prior database defaults.
    op.alter_column(
        "resident_leases",
        "status",
        existing_type=sa.String(length=20),
        server_default="draft",
        existing_nullable=False,
    )
    op.alter_column(
        "leases",
        "status",
        existing_type=sa.String(length=50),
        server_default=None,
        existing_nullable=True,
    )

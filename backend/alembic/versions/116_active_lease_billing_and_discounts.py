"""Add monthly active-lease usage and tracked subscription discounts.

Revision ID: 116
Revises: 115
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "active_lease_months",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lease_type", sa.String(20), nullable=False),
        sa.Column("lease_id", UUID(as_uuid=True), nullable=False),
        sa.Column("period_month", sa.String(7), nullable=False),
        sa.Column(
            "first_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "lease_type",
            "lease_id",
            "period_month",
            name="uq_active_lease_month_org_lease_period",
        ),
    )
    op.create_index(
        "idx_active_lease_month_org_period",
        "active_lease_months",
        ["organization_id", "period_month"],
    )

    op.create_table(
        "subscription_discount_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("stripe_coupon_id", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "stripe_promotion_code_id", sa.String(255), nullable=False, unique=True
        ),
        sa.Column("discount_type", sa.String(20), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_off_cents", sa.Integer(), nullable=True),
        sa.Column("duration", sa.String(20), nullable=False),
        sa.Column("duration_in_months", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("times_redeemed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("code", name="uq_subscription_discount_codes_code"),
    )
    op.create_index(
        "idx_subscription_discount_codes_code",
        "subscription_discount_codes",
        ["code"],
    )

    op.create_table(
        "subscription_discount_redemptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discount_code_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscription_discount_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stripe_checkout_session_id", sa.String(255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "discount_code_id",
            "organization_id",
            "stripe_checkout_session_id",
            name="uq_subscription_discount_redemption_session",
        ),
    )
    op.create_index(
        "idx_subscription_discount_redemption_org",
        "subscription_discount_redemptions",
        ["organization_id"],
    )

    # A lease already Active when this release is deployed counts for the
    # current month. Future months are recorded only when the lease is saved as
    # Active in that month, preserving the stated "at least one day" rule.
    op.execute(
        sa.text(
            """
            INSERT INTO active_lease_months
                (id, organization_id, lease_type, lease_id, period_month, first_active_at)
            SELECT gen_random_uuid(), organization_id, 'commercial', id,
                   to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM'), now()
            FROM leases
            WHERE organization_id IS NOT NULL
              AND is_deleted = false
              AND lower(coalesce(status, '')) = 'active'
            ON CONFLICT ON CONSTRAINT uq_active_lease_month_org_lease_period DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO active_lease_months
                (id, organization_id, lease_type, lease_id, period_month, first_active_at)
            SELECT gen_random_uuid(), organization_id, 'residential', id,
                   to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM'), now()
            FROM resident_leases
            WHERE organization_id IS NOT NULL
              AND is_deleted = false
              AND lower(coalesce(status, '')) = 'active'
            ON CONFLICT ON CONSTRAINT uq_active_lease_month_org_lease_period DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "idx_subscription_discount_redemption_org",
        table_name="subscription_discount_redemptions",
    )
    op.drop_table("subscription_discount_redemptions")
    op.drop_index(
        "idx_subscription_discount_codes_code",
        table_name="subscription_discount_codes",
    )
    op.drop_table("subscription_discount_codes")
    op.drop_index(
        "idx_active_lease_month_org_period", table_name="active_lease_months"
    )
    op.drop_table("active_lease_months")

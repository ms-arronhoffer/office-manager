"""Add persisted billing ledger (subscriptions, invoices, charges, refunds, credits, coupons).

Phase 1 of the billing/payments admin engine: durable revenue tables mirroring
Stripe objects so MRR/ARR and reconciliation can be driven by real data instead
of plan-count estimates.

Revision ID: 061
Revises: 060
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="stripe"),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(20), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("interval", sa.String(10), nullable=False, server_default="month"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coupon_code", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_subscription_id"),
    )
    op.create_index("ix_billing_subscriptions_organization_id", "billing_subscriptions", ["organization_id"])
    op.create_index("ix_billing_subscriptions_stripe_subscription_id", "billing_subscriptions", ["stripe_subscription_id"])
    op.create_index("ix_billing_subscriptions_stripe_customer_id", "billing_subscriptions", ["stripe_customer_id"])

    op.create_table(
        "billing_invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="stripe"),
        sa.Column("stripe_invoice_id", sa.String(255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("number", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("subtotal_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("amount_paid_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("amount_due_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hosted_invoice_url", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_invoice_id"),
    )
    op.create_index("ix_billing_invoices_organization_id", "billing_invoices", ["organization_id"])
    op.create_index("ix_billing_invoices_stripe_invoice_id", "billing_invoices", ["stripe_invoice_id"])
    op.create_index("ix_billing_invoices_stripe_customer_id", "billing_invoices", ["stripe_customer_id"])
    op.create_index("ix_billing_invoices_stripe_subscription_id", "billing_invoices", ["stripe_subscription_id"])

    op.create_table(
        "billing_charges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="stripe"),
        sa.Column("stripe_charge_id", sa.String(255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="succeeded"),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("amount_refunded_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("failure_message", sa.String(500), nullable=True),
        sa.Column("charged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_charge_id"),
    )
    op.create_index("ix_billing_charges_organization_id", "billing_charges", ["organization_id"])
    op.create_index("ix_billing_charges_stripe_charge_id", "billing_charges", ["stripe_charge_id"])
    op.create_index("ix_billing_charges_stripe_customer_id", "billing_charges", ["stripe_customer_id"])
    op.create_index("ix_billing_charges_stripe_invoice_id", "billing_charges", ["stripe_invoice_id"])

    op.create_table(
        "billing_refunds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="stripe"),
        sa.Column("stripe_refund_id", sa.String(255), nullable=True),
        sa.Column("stripe_charge_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="succeeded"),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("reason", sa.String(100), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_refund_id"),
    )
    op.create_index("ix_billing_refunds_organization_id", "billing_refunds", ["organization_id"])
    op.create_index("ix_billing_refunds_stripe_refund_id", "billing_refunds", ["stripe_refund_id"])
    op.create_index("ix_billing_refunds_stripe_charge_id", "billing_refunds", ["stripe_charge_id"])

    op.create_table(
        "billing_credits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_credits_organization_id", "billing_credits", ["organization_id"])

    op.create_table(
        "billing_coupons",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="stripe"),
        sa.Column("stripe_coupon_id", sa.String(255), nullable=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_off_cents", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("duration", sa.String(20), nullable=False, server_default="once"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_coupon_id"),
    )
    op.create_index("ix_billing_coupons_stripe_coupon_id", "billing_coupons", ["stripe_coupon_id"])


def downgrade() -> None:
    op.drop_table("billing_coupons")
    op.drop_table("billing_credits")
    op.drop_table("billing_refunds")
    op.drop_table("billing_charges")
    op.drop_table("billing_invoices")
    op.drop_table("billing_subscriptions")

"""Add Plaid Auth and Stripe ACH resident payment lifecycle.

Revision ID: 122
Revises: 121
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None

_PREDICATE = """(
    current_setting('app.rls_bypass', true) = 'on'
    OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
)"""


def _enable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"')
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def upgrade() -> None:
    op.add_column("organization_integration_configs", sa.Column("webhook_secret_encrypted", sa.Text()))
    op.add_column("organization_integration_configs", sa.Column("webhook_key", sa.String(64)))
    op.create_unique_constraint(
        "uq_org_integration_config_webhook_key", "organization_integration_configs", ["webhook_key"]
    )

    op.add_column("resident_payment_methods", sa.Column("method_type", sa.String(12), server_default="card", nullable=False))
    op.add_column("resident_payment_methods", sa.Column("status", sa.String(24), server_default="active", nullable=False))
    op.add_column("resident_payment_methods", sa.Column("stripe_customer_id", sa.String(255)))
    op.add_column("resident_payment_methods", sa.Column("bank_name", sa.String(120)))
    op.add_column("resident_payment_methods", sa.Column("account_type", sa.String(40)))
    op.add_column("resident_payment_methods", sa.Column("consent_version", sa.String(40)))
    op.add_column("resident_payment_methods", sa.Column("consent_text", sa.Text()))
    op.add_column("resident_payment_methods", sa.Column("consented_at", sa.DateTime(timezone=True)))
    op.add_column("resident_payment_methods", sa.Column("consent_ip", sa.String(64)))
    op.add_column("resident_payment_methods", sa.Column("consent_user_agent", sa.String(500)))
    op.add_column("resident_payment_methods", sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("resident_payment_methods", sa.Column("last_failed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint("ck_resident_payment_method_type", "resident_payment_methods", "method_type IN ('card','ach')")
    op.create_check_constraint(
        "ck_resident_payment_method_status", "resident_payment_methods",
        "status IN ('active','verification_pending','failed','revoked')",
    )
    op.alter_column("resident_payment_methods", "organization_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    _enable_rls("resident_payment_methods")

    for name, column_type in (
        ("autopay_consent_version", sa.String(40)),
        ("autopay_consent_text", sa.Text()),
        ("autopay_consented_at", sa.DateTime(timezone=True)),
        ("autopay_consent_ip", sa.String(64)),
        ("autopay_consent_user_agent", sa.String(500)),
    ):
        op.add_column("resident_leases", sa.Column(name, column_type))

    op.add_column("customer_receipts", sa.Column("reversed_at", sa.DateTime(timezone=True)))
    op.add_column("customer_receipts", sa.Column("reversal_journal_entry_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_customer_receipts_reversal_journal", "customer_receipts", "journal_entries",
        ["reversal_journal_entry_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "resident_payment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True)),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payment_method_id", postgresql.UUID(as_uuid=True)),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("method_type", sa.String(12), nullable=False),
        sa.Column("processor_ref", sa.String(255)),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), server_default="processing", nullable=False),
        sa.Column("allocation_json", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("return_code", sa.String(100)),
        sa.Column("failure_detail", sa.Text()),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("method_type IN ('card','ach')", name="ck_resident_payment_attempt_method"),
        sa.CheckConstraint(
            "status IN ('processing','succeeded','failed','returned','canceled')",
            name="ck_resident_payment_attempt_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resident_id"], ["residents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lease_id"], ["resident_leases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invoice_id"], ["customer_invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_method_id"], ["resident_payment_methods.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["receipt_id"], ["customer_receipts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_resident_payment_attempt_org_key"),
    )
    op.create_index("ix_resident_payment_attempts_organization_id", "resident_payment_attempts", ["organization_id"])
    op.create_index("ix_resident_payment_attempts_resident_id", "resident_payment_attempts", ["resident_id"])
    op.create_index("ix_resident_payment_attempts_processor_ref", "resident_payment_attempts", ["processor_ref"])
    _enable_rls("resident_payment_attempts")

    op.create_table(
        "resident_payment_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stripe_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("processor_ref", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "stripe_event_id", name="uq_resident_payment_webhook_org_event"),
    )
    op.create_index("ix_resident_payment_webhook_events_organization_id", "resident_payment_webhook_events", ["organization_id"])
    _enable_rls("resident_payment_webhook_events")


def downgrade() -> None:
    op.drop_table("resident_payment_webhook_events")
    op.drop_table("resident_payment_attempts")
    op.drop_constraint("fk_customer_receipts_reversal_journal", "customer_receipts", type_="foreignkey")
    op.drop_column("customer_receipts", "reversal_journal_entry_id")
    op.drop_column("customer_receipts", "reversed_at")
    for name in (
        "autopay_consent_user_agent", "autopay_consent_ip", "autopay_consented_at",
        "autopay_consent_text", "autopay_consent_version",
    ):
        op.drop_column("resident_leases", name)
    op.drop_constraint("ck_resident_payment_method_status", "resident_payment_methods", type_="check")
    op.drop_constraint("ck_resident_payment_method_type", "resident_payment_methods", type_="check")
    for name in (
        "last_failed_at", "failure_count", "consent_user_agent", "consent_ip", "consented_at",
        "consent_text", "consent_version", "account_type", "bank_name", "stripe_customer_id",
        "status", "method_type",
    ):
        op.drop_column("resident_payment_methods", name)
    op.drop_constraint("uq_org_integration_config_webhook_key", "organization_integration_configs", type_="unique")
    op.drop_column("organization_integration_configs", "webhook_key")
    op.drop_column("organization_integration_configs", "webhook_secret_encrypted")

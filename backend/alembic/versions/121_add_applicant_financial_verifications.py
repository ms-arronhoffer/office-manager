"""Add applicant financial verification workflow.

Revision ID: 121
Revises: 120
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None

_PREDICATE = """(
    current_setting('app.rls_bypass', true) = 'on'
    OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
)"""


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def upgrade() -> None:
    op.create_table(
        "applicant_financial_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(24), server_default="invited", nullable=False),
        sa.Column("invitation_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("viewed_at", sa.DateTime(timezone=True)),
        sa.Column("consented_at", sa.DateTime(timezone=True)),
        sa.Column("linked_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("consent_text", sa.Text()),
        sa.Column("consent_version", sa.String(40)),
        sa.Column("consent_ip", sa.String(64)),
        sa.Column("consent_user_agent", sa.String(500)),
        sa.Column("access_token_encrypted", sa.Text()),
        sa.Column("item_id", sa.String(100)),
        sa.Column("institution_name", sa.String(255)),
        sa.Column("account_count", sa.Integer()),
        sa.Column("summary_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("identity_match", sa.Boolean()),
        sa.Column("ownership_match", sa.Boolean()),
        sa.Column("available_balance_total", sa.Numeric(15, 2)),
        sa.Column("current_balance_total", sa.Numeric(15, 2)),
        sa.Column("recurring_income_monthly", sa.Numeric(15, 2)),
        sa.Column("income_months_observed", sa.Integer()),
        sa.Column("recommendation", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.Column("last_webhook_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('invited','viewed','consented','linking','processing','completed','action_required','declined','expired','error','revoked')", name="ck_financial_verification_status"),
        sa.CheckConstraint("recommendation IN ('verified','review','insufficient','unknown')", name="ck_financial_verification_recommendation"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["rental_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invitation_token_hash"),
    )
    op.create_index("ix_applicant_financial_verifications_organization_id", "applicant_financial_verifications", ["organization_id"])
    op.create_index("ix_applicant_financial_verifications_application", "applicant_financial_verifications", ["application_id"])
    op.create_index("ix_applicant_financial_verifications_item_id", "applicant_financial_verifications", ["item_id"])
    op.create_index("ix_applicant_financial_verifications_invitation_token_hash", "applicant_financial_verifications", ["invitation_token_hash"], unique=True)
    _enable_rls("applicant_financial_verifications")

    op.create_table(
        "financial_verification_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_digest", sa.String(64), nullable=False),
        sa.Column("webhook_type", sa.String(50), nullable=False),
        sa.Column("webhook_code", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verification_id"], ["applicant_financial_verifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_digest", name="uq_financial_verification_webhook_digest"),
    )
    op.create_index("ix_financial_verification_webhook_events_organization_id", "financial_verification_webhook_events", ["organization_id"])
    op.create_index("ix_financial_verification_webhook_events_verification_id", "financial_verification_webhook_events", ["verification_id"])
    _enable_rls("financial_verification_webhook_events")


def downgrade() -> None:
    op.drop_table("financial_verification_webhook_events")
    op.drop_table("applicant_financial_verifications")
"""Add digital waiver tables (templates, requests, signatures).

Revision ID: 048
Revises: 047
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waiver_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_prebuilt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("prebuilt_key", sa.String(length=60), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_waiver_templates_organization_id", "waiver_templates", ["organization_id"])
    op.create_index("ix_waiver_templates_prebuilt_key", "waiver_templates", ["prebuilt_key"])

    op.create_table(
        "waiver_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("recipient_type", sa.String(length=20), nullable=False),
        sa.Column("recipient_name", sa.String(length=200), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("entity_contact_id", sa.UUID(), nullable=True),
        sa.Column("visitor_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("rendered_body", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="sent"),
        sa.Column("sign_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["waiver_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sign_token"),
    )
    op.create_index("ix_waiver_requests_organization_id", "waiver_requests", ["organization_id"])
    op.create_index("ix_waiver_requests_sign_token", "waiver_requests", ["sign_token"])

    op.create_table(
        "waiver_signatures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("signer_name", sa.String(length=200), nullable=False),
        sa.Column("signer_email", sa.String(length=320), nullable=True),
        sa.Column("signature_type", sa.String(length=20), nullable=False, server_default="typed"),
        sa.Column("signature_data", sa.Text(), nullable=False),
        sa.Column("consent_text", sa.Text(), nullable=True),
        sa.Column("consent_agreed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["waiver_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_waiver_signatures_request_id", "waiver_signatures", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_waiver_signatures_request_id", table_name="waiver_signatures")
    op.drop_table("waiver_signatures")
    op.drop_index("ix_waiver_requests_sign_token", table_name="waiver_requests")
    op.drop_index("ix_waiver_requests_organization_id", table_name="waiver_requests")
    op.drop_table("waiver_requests")
    op.drop_index("ix_waiver_templates_prebuilt_key", table_name="waiver_templates")
    op.drop_index("ix_waiver_templates_organization_id", table_name="waiver_templates")
    op.drop_table("waiver_templates")

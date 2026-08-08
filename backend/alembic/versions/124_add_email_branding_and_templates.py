"""Organization-controlled email branding and template overrides.

Lets a customer put their own sender name, reply-to address, logo, colours,
signature and footer on the mail the product sends for them, and override the
subject and body of individual message types without touching the filesystem.

Revision ID: 124
Revises: 123
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "124"
down_revision = "123"
branch_labels = None
depends_on = None

_PREDICATE = """(
    current_setting('app.rls_bypass', true) = 'on'
    OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
)"""

_RLS_TABLES = ("email_branding", "email_templates")


def _enable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"')
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def upgrade() -> None:
    op.create_table(
        "email_branding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("sender_name", sa.String(120), nullable=True),
        sa.Column("reply_to", sa.String(255), nullable=True),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("header_color", sa.String(9), nullable=False, server_default="#232f3e"),
        sa.Column("accent_color", sa.String(9), nullable=False, server_default="#0972d3"),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("footer_text", sa.Text(), nullable=True),
        sa.Column("postal_address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", name="uq_email_branding_org"),
    )
    op.create_index("idx_email_branding_org", "email_branding", ["organization_id"])

    op.create_table(
        "email_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("template_key", sa.String(60), nullable=False),
        sa.Column("subject_template", sa.String(500), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "template_key", name="uq_email_template_org_key"),
    )
    op.create_index("idx_email_templates_org", "email_templates", ["organization_id"])
    op.create_index("idx_email_templates_key", "email_templates", ["template_key"])

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"')
    op.drop_table("email_templates")
    op.drop_table("email_branding")

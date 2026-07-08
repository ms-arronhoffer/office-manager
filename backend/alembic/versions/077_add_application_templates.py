"""Add application templates + send-by-email/e-sign fields to rental applications

Creates the ``application_templates`` table (reusable, org-scoped residential
application documents with merge fields and an optional structured field schema)
and extends ``rental_applications`` so a staff-sent, template-based application
can be emailed to a named person and e-signed by the applicant, carrying the same
ESIGN/UETA evidentiary trail used for lease signing.

Revision ID: 077
Revises: 076
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("field_schema", postgresql.JSONB(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_templates_organization_id",
        "application_templates",
        ["organization_id"],
    )
    op.create_index(
        "idx_application_templates_org", "application_templates", ["organization_id"]
    )
    op.create_index(
        "idx_application_templates_active", "application_templates", ["is_active"]
    )

    op.add_column(
        "rental_applications",
        sa.Column("application_template_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "rental_applications", sa.Column("invite_token", sa.String(64), nullable=True)
    )
    op.add_column(
        "rental_applications", sa.Column("sent_by_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "rental_applications",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rental_applications",
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rental_applications",
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rental_applications", sa.Column("rendered_body", sa.Text(), nullable=True)
    )
    op.add_column(
        "rental_applications", sa.Column("document_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "rental_applications", sa.Column("signature_type", sa.String(20), nullable=True)
    )
    op.add_column(
        "rental_applications", sa.Column("signature_data", sa.Text(), nullable=True)
    )
    op.add_column(
        "rental_applications", sa.Column("consent_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "rental_applications",
        sa.Column(
            "consent_agreed", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "rental_applications", sa.Column("ip_address", sa.String(64), nullable=True)
    )
    op.add_column(
        "rental_applications", sa.Column("user_agent", sa.String(500), nullable=True)
    )
    op.create_foreign_key(
        "fk_rental_applications_application_template",
        "rental_applications",
        "application_templates",
        ["application_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_rental_applications_sent_by",
        "rental_applications",
        "users",
        ["sent_by_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_rental_applications_invite_token", "rental_applications", ["invite_token"]
    )
    op.create_index(
        "ix_rental_applications_invite_token",
        "rental_applications",
        ["invite_token"],
    )


def downgrade() -> None:
    op.drop_index("ix_rental_applications_invite_token", "rental_applications")
    op.drop_constraint(
        "uq_rental_applications_invite_token", "rental_applications", type_="unique"
    )
    op.drop_constraint(
        "fk_rental_applications_sent_by", "rental_applications", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_rental_applications_application_template",
        "rental_applications",
        type_="foreignkey",
    )
    for col in (
        "user_agent",
        "ip_address",
        "consent_agreed",
        "consent_text",
        "signature_data",
        "signature_type",
        "document_hash",
        "rendered_body",
        "signed_at",
        "viewed_at",
        "sent_at",
        "sent_by_id",
        "invite_token",
        "application_template_id",
    ):
        op.drop_column("rental_applications", col)

    op.drop_index("idx_application_templates_active", "application_templates")
    op.drop_index("idx_application_templates_org", "application_templates")
    op.drop_index(
        "ix_application_templates_organization_id", "application_templates"
    )
    op.drop_table("application_templates")

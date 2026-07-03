"""Add leasing funnel: applications, screening, lease e-sign (Phase 2.4)

Revision ID: 071
Revises: 070
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rental_applications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("unit_id", sa.UUID(), nullable=True),
        sa.Column("applicant_first_name", sa.String(100), nullable=False),
        sa.Column("applicant_last_name", sa.String(100), nullable=False),
        sa.Column("applicant_email", sa.String(320), nullable=False),
        sa.Column("applicant_phone", sa.String(50), nullable=True),
        sa.Column("desired_move_in", sa.Date(), nullable=True),
        sa.Column("monthly_income", sa.Numeric(15, 2), nullable=True),
        sa.Column("application_data", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.UUID(), nullable=True),
        sa.Column("resident_id", sa.UUID(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["rental_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["resident_id"], ["residents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rental_applications_organization_id", "rental_applications", ["organization_id"])
    op.create_index("idx_rental_applications_unit", "rental_applications", ["unit_id"])
    op.create_index("idx_rental_applications_status", "rental_applications", ["status"])

    op.create_table(
        "screening_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("application_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("recommendation", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("credit_score", sa.Integer(), nullable=True),
        sa.Column("external_ref", sa.String(100), nullable=True),
        sa.Column("report_data", postgresql.JSONB(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["application_id"], ["rental_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_screening_reports_organization_id", "screening_reports", ["organization_id"])
    op.create_index("idx_screening_reports_application", "screening_reports", ["application_id"])

    op.create_table(
        "lease_signature_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("resident_lease_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("rendered_body", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["resident_lease_id"], ["resident_leases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lease_signature_requests_organization_id", "lease_signature_requests", ["organization_id"])
    op.create_index("idx_lease_sign_requests_lease", "lease_signature_requests", ["resident_lease_id"])
    op.create_index("idx_lease_sign_requests_status", "lease_signature_requests", ["status"])

    op.create_table(
        "lease_signature_parties",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("signer_name", sa.String(200), nullable=False),
        sa.Column("signer_email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="tenant"),
        sa.Column("sign_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sign_token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("signature_type", sa.String(20), nullable=True),
        sa.Column("signature_data", sa.Text(), nullable=True),
        sa.Column("consent_text", sa.Text(), nullable=True),
        sa.Column("consent_agreed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("document_hash", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["lease_signature_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sign_token", name="uq_lease_signature_party_token"),
    )
    op.create_index("idx_lease_sign_parties_request", "lease_signature_parties", ["request_id"])
    op.create_index("ix_lease_signature_parties_sign_token", "lease_signature_parties", ["sign_token"])


def downgrade() -> None:
    op.drop_table("lease_signature_parties")
    op.drop_table("lease_signature_requests")
    op.drop_table("screening_reports")
    op.drop_table("rental_applications")

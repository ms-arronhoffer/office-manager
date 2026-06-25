"""add insurance certificates table

Revision ID: 029
Revises: 028
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insurance_certificates",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("vendor_id", sa.UUID(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=True),
        sa.Column("landlord_id", sa.UUID(), sa.ForeignKey("landlords.id", ondelete="CASCADE"), nullable=True),
        sa.Column("certificate_type", sa.String(50), nullable=False),
        sa.Column("insurer", sa.String(255), nullable=True),
        sa.Column("policy_number", sa.String(100), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("limits", sa.Text(), nullable=True),
        sa.Column("certificate_holder", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("idx_inscert_vendor", "insurance_certificates", ["vendor_id"])
    op.create_index("idx_inscert_landlord", "insurance_certificates", ["landlord_id"])
    op.create_index("idx_inscert_expiration", "insurance_certificates", ["expiration_date"])
    op.create_index("idx_inscert_org", "insurance_certificates", ["organization_id"])


def downgrade() -> None:
    op.drop_index("idx_inscert_org", table_name="insurance_certificates")
    op.drop_index("idx_inscert_expiration", table_name="insurance_certificates")
    op.drop_index("idx_inscert_landlord", table_name="insurance_certificates")
    op.drop_index("idx_inscert_vendor", table_name="insurance_certificates")
    op.drop_table("insurance_certificates")

"""add vendors and vendor_offices tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("services", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_vendors_company_name", "vendors", ["company_name"])
    op.create_index("idx_vendors_is_preferred", "vendors", ["is_preferred"])

    op.create_table(
        "vendor_offices",
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("office_id", sa.Uuid(), sa.ForeignKey("offices.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("vendor_id", "office_id"),
    )
    op.create_index("idx_vendor_offices_office_id", "vendor_offices", ["office_id"])


def downgrade() -> None:
    op.drop_table("vendor_offices")
    op.drop_index("idx_vendors_is_preferred", table_name="vendors")
    op.drop_index("idx_vendors_company_name", table_name="vendors")
    op.drop_table("vendors")

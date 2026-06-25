"""add vendor portal token and ticket vendor assignment

Revision ID: 028
Revises: 027
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("portal_token", sa.String(64), nullable=True, unique=True))
    op.add_column("vendors", sa.Column("portal_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_vendors_portal_token", "vendors", ["portal_token"])

    op.add_column("maintenance_tickets", sa.Column("vendor_id", sa.UUID(), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("vendor_completion_notes", sa.Text(), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("vendor_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_maintenance_tickets_vendor_id",
        "maintenance_tickets", "vendors",
        ["vendor_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_maint_ticket_vendor", "maintenance_tickets", ["vendor_id"])


def downgrade() -> None:
    op.drop_index("idx_maint_ticket_vendor", table_name="maintenance_tickets")
    op.drop_constraint("fk_maintenance_tickets_vendor_id", "maintenance_tickets", type_="foreignkey")
    op.drop_column("maintenance_tickets", "vendor_completed_at")
    op.drop_column("maintenance_tickets", "vendor_completion_notes")
    op.drop_column("maintenance_tickets", "vendor_id")

    op.drop_index("idx_vendors_portal_token", table_name="vendors")
    op.drop_column("vendors", "portal_token_expires_at")
    op.drop_column("vendors", "portal_token")

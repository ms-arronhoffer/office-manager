"""Add resident communications + resident-submitted maintenance (Phase 2.2)

Revision ID: 069
Revises: 068
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provenance for resident-submitted maintenance requests.
    op.add_column(
        "maintenance_tickets",
        sa.Column("submitted_by_resident_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_maintenance_tickets_resident",
        "maintenance_tickets",
        "residents",
        ["submitted_by_resident_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_maint_ticket_resident",
        "maintenance_tickets",
        ["submitted_by_resident_id"],
    )

    op.create_table(
        "announcements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("channels", sa.String(100), nullable=False, server_default="portal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("audience_office_id", sa.UUID(), nullable=True),
        sa.Column("audience_resident_status", sa.String(20), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["audience_office_id"], ["offices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_announcements_org", "announcements", ["organization_id"])
    op.create_index("idx_announcements_status", "announcements", ["status"])
    op.create_index("ix_announcements_organization_id", "announcements", ["organization_id"])

    op.create_table(
        "announcement_recipients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("announcement_id", sa.UUID(), nullable=False),
        sa.Column("resident_id", sa.UUID(), nullable=False),
        sa.Column("emailed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("texted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resident_id"], ["residents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_announcement_recipients_ann", "announcement_recipients", ["announcement_id"]
    )
    op.create_index(
        "idx_announcement_recipients_resident", "announcement_recipients", ["resident_id"]
    )


def downgrade() -> None:
    op.drop_table("announcement_recipients")
    op.drop_table("announcements")
    op.drop_index("idx_maint_ticket_resident", table_name="maintenance_tickets")
    op.drop_constraint(
        "fk_maintenance_tickets_resident", "maintenance_tickets", type_="foreignkey"
    )
    op.drop_column("maintenance_tickets", "submitted_by_resident_id")

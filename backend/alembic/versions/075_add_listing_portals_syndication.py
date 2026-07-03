"""Add listing portals & syndication

Adds portal-distribution tables backing the syndication of vacancy listings to
external listing sites (Zillow, Homes.com, Apartments.com, …) and custom
portals: ``listing_portals`` (configured portal targets) and
``listing_syndications`` (per-listing, per-portal distribution records).

Revision ID: 075
Revises: 074
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listing_portals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False, server_default="custom"),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("endpoint_url", sa.String(500), nullable=True),
        sa.Column("delivery_mode", sa.String(20), nullable=False, server_default="feed"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_listing_portals_org", "listing_portals", ["organization_id"])

    op.create_table(
        "listing_syndications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("portal_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["listing_id"], ["vacancy_listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portal_id"], ["listing_portals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "portal_id", name="uq_listing_syndication"),
    )
    op.create_index("idx_listing_syndications_org", "listing_syndications", ["organization_id"])
    op.create_index("idx_listing_syndications_listing", "listing_syndications", ["listing_id"])
    op.create_index("idx_listing_syndications_portal", "listing_syndications", ["portal_id"])


def downgrade() -> None:
    op.drop_index("idx_listing_syndications_portal", table_name="listing_syndications")
    op.drop_index("idx_listing_syndications_listing", table_name="listing_syndications")
    op.drop_index("idx_listing_syndications_org", table_name="listing_syndications")
    op.drop_table("listing_syndications")
    op.drop_index("idx_listing_portals_org", table_name="listing_portals")
    op.drop_table("listing_portals")

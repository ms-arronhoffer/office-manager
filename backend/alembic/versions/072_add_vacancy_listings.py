"""Add vacancy listings & syndication (Phase 2.5)

Revision ID: 072
Revises: 071
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vacancy_listings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("unit_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("headline", sa.String(300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("marketing_rent", sa.Numeric(15, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("available_date", sa.Date(), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Numeric(4, 1), nullable=True),
        sa.Column("square_feet", sa.Numeric(12, 2), nullable=True),
        sa.Column("amenities", postgresql.JSONB(), nullable=True),
        sa.Column("photos", postgresql.JSONB(), nullable=True),
        sa.Column("application_url", sa.String(500), nullable=True),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["rental_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vacancy_listings_organization_id", "vacancy_listings", ["organization_id"])
    op.create_index("idx_vacancy_listings_unit", "vacancy_listings", ["unit_id"])
    op.create_index("idx_vacancy_listings_status", "vacancy_listings", ["status"])


def downgrade() -> None:
    op.drop_table("vacancy_listings")

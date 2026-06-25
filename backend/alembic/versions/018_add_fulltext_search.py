"""add full-text search vectors

Revision ID: 018
Revises: 017
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tsvector columns
    op.add_column("offices", sa.Column("search_vector", sa.Text, nullable=True))
    op.add_column("leases", sa.Column("search_vector", sa.Text, nullable=True))
    op.add_column("maintenance_tickets", sa.Column("search_vector", sa.Text, nullable=True))
    op.add_column("landlords", sa.Column("search_vector", sa.Text, nullable=True))

    # Alter columns to tsvector type using raw SQL (SQLAlchemy Text → tsvector)
    op.execute("ALTER TABLE offices ALTER COLUMN search_vector TYPE tsvector USING NULL")
    op.execute("ALTER TABLE leases ALTER COLUMN search_vector TYPE tsvector USING NULL")
    op.execute("ALTER TABLE maintenance_tickets ALTER COLUMN search_vector TYPE tsvector USING NULL")
    op.execute("ALTER TABLE landlords ALTER COLUMN search_vector TYPE tsvector USING NULL")

    # Populate initial values
    op.execute(
        "UPDATE offices SET search_vector = "
        "to_tsvector('english', coalesce(location_name,'') || ' ' || coalesce(city,'') || ' ' || coalesce(notes,''))"
    )
    op.execute(
        "UPDATE leases SET search_vector = "
        "to_tsvector('english', coalesce(lease_name,'') || ' ' || coalesce(lessor_name,''))"
    )
    op.execute(
        "UPDATE maintenance_tickets SET search_vector = "
        "to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(description,''))"
    )
    op.execute(
        "UPDATE landlords SET search_vector = "
        "to_tsvector('english', coalesce(landlord_company,'') || ' ' || coalesce(contact_name,''))"
    )

    # GIN indexes for fast full-text search
    op.execute("CREATE INDEX idx_offices_fts ON offices USING GIN(search_vector) WHERE search_vector IS NOT NULL")
    op.execute("CREATE INDEX idx_leases_fts ON leases USING GIN(search_vector) WHERE search_vector IS NOT NULL")
    op.execute("CREATE INDEX idx_tickets_fts ON maintenance_tickets USING GIN(search_vector) WHERE search_vector IS NOT NULL")
    op.execute("CREATE INDEX idx_landlords_fts ON landlords USING GIN(search_vector) WHERE search_vector IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_offices_fts")
    op.execute("DROP INDEX IF EXISTS idx_leases_fts")
    op.execute("DROP INDEX IF EXISTS idx_tickets_fts")
    op.execute("DROP INDEX IF EXISTS idx_landlords_fts")
    op.drop_column("offices", "search_vector")
    op.drop_column("leases", "search_vector")
    op.drop_column("maintenance_tickets", "search_vector")
    op.drop_column("landlords", "search_vector")

"""Improve landlord data collection

Adds business/billing data points to landlords, contact typing to landlord
contacts, and a landlord_offices association table so a landlord can own one
or many offices.

Revision ID: 042
Revises: 041
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New landlord data points.
    op.add_column("landlords", sa.Column("secondary_phone", sa.Text(), nullable=True))
    op.add_column("landlords", sa.Column("fax", sa.Text(), nullable=True))
    op.add_column("landlords", sa.Column("website", sa.String(255), nullable=True))
    op.add_column("landlords", sa.Column("entity_type", sa.String(50), nullable=True))
    op.add_column("landlords", sa.Column("tax_id", sa.String(50), nullable=True))
    op.add_column("landlords", sa.Column("management_company", sa.String(255), nullable=True))
    op.add_column("landlords", sa.Column("preferred_payment_method", sa.String(50), nullable=True))
    op.add_column("landlords", sa.Column("payment_terms", sa.String(100), nullable=True))

    # Contact typing.
    op.add_column("landlord_contacts", sa.Column("contact_type", sa.String(50), nullable=True))
    op.add_column(
        "landlord_contacts",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Many-to-many: offices owned by a landlord.
    op.create_table(
        "landlord_offices",
        sa.Column("landlord_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("landlord_id", "office_id"),
    )
    op.create_index("idx_landlord_offices_office_id", "landlord_offices", ["office_id"])


def downgrade() -> None:
    op.drop_index("idx_landlord_offices_office_id", table_name="landlord_offices")
    op.drop_table("landlord_offices")

    op.drop_column("landlord_contacts", "is_primary")
    op.drop_column("landlord_contacts", "contact_type")

    op.drop_column("landlords", "payment_terms")
    op.drop_column("landlords", "preferred_payment_method")
    op.drop_column("landlords", "management_company")
    op.drop_column("landlords", "tax_id")
    op.drop_column("landlords", "entity_type")
    op.drop_column("landlords", "website")
    op.drop_column("landlords", "fax")
    op.drop_column("landlords", "secondary_phone")

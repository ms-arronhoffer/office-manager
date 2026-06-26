"""Add property-owner fields to offices.

An office's landlord and its legal property owner may be different parties, so
offices gain a dedicated set of owner contact/address columns plus an
``owner_same_as_landlord`` flag the UI uses to mirror the landlord details.

Revision ID: 051
Revises: 050
"""
import sqlalchemy as sa
from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offices",
        sa.Column(
            "owner_same_as_landlord",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("offices", sa.Column("owner_name", sa.String(length=255), nullable=True))
    op.add_column("offices", sa.Column("owner_company", sa.String(length=255), nullable=True))
    op.add_column("offices", sa.Column("owner_email", sa.String(length=255), nullable=True))
    op.add_column("offices", sa.Column("owner_phone", sa.Text(), nullable=True))
    op.add_column("offices", sa.Column("owner_address_line_1", sa.String(length=255), nullable=True))
    op.add_column("offices", sa.Column("owner_address_line_2", sa.String(length=255), nullable=True))
    op.add_column("offices", sa.Column("owner_city", sa.String(length=100), nullable=True))
    op.add_column("offices", sa.Column("owner_state", sa.String(length=2), nullable=True))
    op.add_column("offices", sa.Column("owner_zip_code", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("offices", "owner_zip_code")
    op.drop_column("offices", "owner_state")
    op.drop_column("offices", "owner_city")
    op.drop_column("offices", "owner_address_line_2")
    op.drop_column("offices", "owner_address_line_1")
    op.drop_column("offices", "owner_phone")
    op.drop_column("offices", "owner_email")
    op.drop_column("offices", "owner_company")
    op.drop_column("offices", "owner_name")
    op.drop_column("offices", "owner_same_as_landlord")

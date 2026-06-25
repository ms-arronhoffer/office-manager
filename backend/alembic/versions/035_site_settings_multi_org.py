"""Make site_settings per-organization

Revision ID: 035
Revises: 034
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add organization_id column
    op.add_column("site_settings", sa.Column("organization_id", sa.UUID(), nullable=True))

    # Add foreign key constraint
    op.create_foreign_key(
        "fk_site_settings_organization_id",
        "site_settings",
        "organizations",
        ["organization_id"],
        ["id"],
    )

    # Change id from Integer to UUID
    op.alter_column("site_settings", "id", existing_type=sa.Integer(), type_=sa.UUID(), existing_nullable=False)

    # Remove the default=1 behavior and change primary key
    op.drop_constraint("site_settings_pkey", "site_settings", type_="primary")
    op.create_primary_key("site_settings_pkey", "site_settings", ["id"])

    # Make organization_id not null (after migration)
    op.alter_column("site_settings", "organization_id", existing_type=sa.UUID(), nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_site_settings_organization_id", "site_settings", type_="foreignkey")
    op.drop_column("site_settings", "organization_id")
    op.alter_column("site_settings", "id", existing_type=sa.UUID(), type_=sa.Integer(), existing_nullable=False)

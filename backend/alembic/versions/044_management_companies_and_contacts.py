"""Add management companies and polymorphic entity contacts

Creates a first-class ``management_companies`` entity, links landlords to it via
``landlords.management_company_id``, and adds a reusable polymorphic
``entity_contacts`` table for additional contacts on any entity.

Revision ID: 044
Revises: 043
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "management_companies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_title", sa.String(100), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("secondary_phone", sa.String(50), nullable=True),
        sa.Column("fax", sa.String(50), nullable=True),
        sa.Column("website", sa.String(255), nullable=True),
        sa.Column("portal_url", sa.String(255), nullable=True),
        sa.Column("address_line_1", sa.String(255), nullable=True),
        sa.Column("address_line_2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("zip_code", sa.String(10), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_management_companies_name", "management_companies", ["name"])
    op.create_index("idx_management_companies_org", "management_companies", ["organization_id"])

    op.add_column("landlords", sa.Column("management_company_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_landlords_management_company_id",
        "landlords",
        "management_companies",
        ["management_company_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_landlords_management_company_id", "landlords", ["management_company_id"])

    op.create_table(
        "entity_contacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(100), nullable=True),
        sa.Column("contact_type", sa.String(50), nullable=True),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("mobile", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_entity_contacts_entity", "entity_contacts", ["entity_type", "entity_id"])
    op.create_index("idx_entity_contacts_org", "entity_contacts", ["organization_id"])


def downgrade() -> None:
    op.drop_index("idx_entity_contacts_org", table_name="entity_contacts")
    op.drop_index("idx_entity_contacts_entity", table_name="entity_contacts")
    op.drop_table("entity_contacts")

    op.drop_index("idx_landlords_management_company_id", table_name="landlords")
    op.drop_constraint("fk_landlords_management_company_id", "landlords", type_="foreignkey")
    op.drop_column("landlords", "management_company_id")

    op.drop_index("idx_management_companies_org", table_name="management_companies")
    op.drop_index("idx_management_companies_name", table_name="management_companies")
    op.drop_table("management_companies")

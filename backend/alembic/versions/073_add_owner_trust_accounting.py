"""Add owner / trust accounting (Phase 2.6)

Revision ID: 073
Revises: 072
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_owners",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("owner_type", sa.String(20), nullable=False, server_default="individual"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("tax_id", sa.String(50), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("state", sa.String(120), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(120), nullable=True),
        sa.Column("management_fee_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_property_owners_organization_id", "property_owners", ["organization_id"])
    op.create_index("idx_property_owners_status", "property_owners", ["status"])
    op.create_index("idx_property_owners_name", "property_owners", ["name"])

    op.create_table(
        "trust_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("bank_name", sa.String(255), nullable=True),
        sa.Column("account_number_last4", sa.String(4), nullable=True),
        sa.Column("gl_account_id", sa.UUID(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("compliance_review_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("compliance_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("compliance_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compliance_reviewed_by_id", sa.UUID(), nullable=True),
        sa.Column("compliance_notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["gl_account_id"], ["gl_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["compliance_reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trust_accounts_organization_id", "trust_accounts", ["organization_id"])
    op.create_index("idx_trust_accounts_status", "trust_accounts", ["status"])
    op.create_index("idx_trust_accounts_compliance", "trust_accounts", ["compliance_status"])

    op.create_table(
        "owner_properties",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("ownership_percent", sa.Numeric(5, 2), nullable=False, server_default="100"),
        sa.Column("management_fee_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["property_owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "office_id", name="uq_owner_property"),
    )
    op.create_index("ix_owner_properties_organization_id", "owner_properties", ["organization_id"])
    op.create_index("idx_owner_properties_owner", "owner_properties", ["owner_id"])
    op.create_index("idx_owner_properties_office", "owner_properties", ["office_id"])

    op.create_table(
        "owner_ledger_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("office_id", sa.UUID(), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["property_owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_ledger_entries_organization_id", "owner_ledger_entries", ["organization_id"])
    op.create_index("idx_owner_ledger_owner", "owner_ledger_entries", ["owner_id"])
    op.create_index("idx_owner_ledger_date", "owner_ledger_entries", ["entry_date"])
    op.create_index("idx_owner_ledger_type", "owner_ledger_entries", ["entry_type"])

    op.create_table(
        "owner_distributions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("distribution_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("method", sa.String(20), nullable=False, server_default="ach"),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("trust_account_id", sa.UUID(), nullable=True),
        sa.Column("ledger_entry_id", sa.UUID(), nullable=True),
        sa.Column("journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["property_owners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trust_account_id"], ["trust_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ledger_entry_id"], ["owner_ledger_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_distributions_organization_id", "owner_distributions", ["organization_id"])
    op.create_index("idx_owner_distributions_owner", "owner_distributions", ["owner_id"])
    op.create_index("idx_owner_distributions_status", "owner_distributions", ["status"])
    op.create_index("idx_owner_distributions_date", "owner_distributions", ["distribution_date"])


def downgrade() -> None:
    op.drop_table("owner_distributions")
    op.drop_table("owner_ledger_entries")
    op.drop_table("owner_properties")
    op.drop_table("trust_accounts")
    op.drop_table("property_owners")

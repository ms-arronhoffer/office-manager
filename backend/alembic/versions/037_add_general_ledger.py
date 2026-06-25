"""Add general-ledger tables (chart of accounts, periods, journal entries)

Revision ID: 037
Revises: 036
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gl_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_gl_accounts_org_code"),
    )
    op.create_index("ix_gl_accounts_organization_id", "gl_accounts", ["organization_id"])

    op.create_table(
        "accounting_periods",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "year", "month", name="uq_accounting_periods_org_ym"),
    )
    op.create_index("ix_accounting_periods_organization_id", "accounting_periods", ["organization_id"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(100), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="posted"),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["period_id"], ["accounting_periods.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["posted_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_entries_organization_id", "journal_entries", ["organization_id"])
    op.create_index("ix_journal_entries_period_id", "journal_entries", ["period_id"])
    op.create_index("ix_journal_entries_source_ref", "journal_entries", ["source_ref"])

    op.create_table(
        "journal_entry_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("debit", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("memo", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["gl_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_entry_lines_entry_id", "journal_entry_lines", ["entry_id"])
    op.create_index("ix_journal_entry_lines_account_id", "journal_entry_lines", ["account_id"])


def downgrade() -> None:
    op.drop_table("journal_entry_lines")
    op.drop_table("journal_entries")
    op.drop_table("accounting_periods")
    op.drop_table("gl_accounts")

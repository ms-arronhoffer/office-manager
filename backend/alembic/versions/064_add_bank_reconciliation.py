"""Add bank-reconciliation tables (Phase 1.2)

Revision ID: 064
Revises: 063
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("gl_account_id", sa.UUID(), nullable=False),
        sa.Column("institution", sa.String(255), nullable=True),
        sa.Column("account_number_last4", sa.String(4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["gl_account_id"], ["gl_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_accounts_organization_id", "bank_accounts", ["organization_id"])
    op.create_index("ix_bank_accounts_gl_account_id", "bank_accounts", ["gl_account_id"])

    op.create_table(
        "bank_reconciliations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("bank_account_id", sa.UUID(), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("beginning_balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("ending_balance", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(15), nullable=False, server_default="in_progress"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_reconciliations_organization_id", "bank_reconciliations", ["organization_id"]
    )
    op.create_index(
        "ix_bank_reconciliations_bank_account_id", "bank_reconciliations", ["bank_account_id"]
    )

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("bank_account_id", sa.UUID(), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("fitid", sa.String(100), nullable=True),
        sa.Column("import_source", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="unmatched"),
        sa.Column("reconciliation_id", sa.UUID(), nullable=True),
        sa.Column("journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"], ["bank_reconciliations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_account_id", "fitid", name="uq_bank_txn_account_fitid"),
    )
    op.create_index(
        "ix_bank_transactions_organization_id", "bank_transactions", ["organization_id"]
    )
    op.create_index(
        "ix_bank_transactions_bank_account_id", "bank_transactions", ["bank_account_id"]
    )
    op.create_index(
        "ix_bank_transactions_reconciliation_id", "bank_transactions", ["reconciliation_id"]
    )


def downgrade() -> None:
    op.drop_table("bank_transactions")
    op.drop_table("bank_reconciliations")
    op.drop_table("bank_accounts")

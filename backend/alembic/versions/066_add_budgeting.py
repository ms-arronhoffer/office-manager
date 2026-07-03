"""Add budgeting tables (Phase 1.4)

GL-account-level annual budgets and their per-account allocation lines, used for
budget-vs-actual variance reporting over the general ledger.

Revision ID: 066
Revises: 065
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="draft"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "fiscal_year", "name", name="uq_budgets_org_year_name"
        ),
    )
    op.create_index("ix_budgets_organization_id", "budgets", ["organization_id"])
    op.create_index("ix_budgets_fiscal_year", "budgets", ["fiscal_year"])

    op.create_table(
        "budget_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("budget_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budgets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["gl_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "budget_id", "account_id", name="uq_budget_lines_budget_account"
        ),
    )
    op.create_index("ix_budget_lines_budget_id", "budget_lines", ["budget_id"])
    op.create_index("ix_budget_lines_account_id", "budget_lines", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_lines_account_id", table_name="budget_lines")
    op.drop_index("ix_budget_lines_budget_id", table_name="budget_lines")
    op.drop_table("budget_lines")
    op.drop_index("ix_budgets_fiscal_year", table_name="budgets")
    op.drop_index("ix_budgets_organization_id", table_name="budgets")
    op.drop_table("budgets")

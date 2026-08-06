"""Extend fail-closed RLS to high-risk financial and portal tables.

Revision ID: 118
Revises: 117
Create Date: 2026-08-06
"""
from alembic import op


revision = "118"
down_revision = "117"
branch_labels = None
depends_on = None


PROTECTED_TABLES = (
    "leases",
    "customers",
    "customer_invoices",
    "customer_receipts",
    "vendor_bills",
    "vendor_payments",
    "gl_accounts",
    "accounting_periods",
    "journal_entries",
    "bank_accounts",
    "bank_transactions",
    "bank_reconciliations",
    "budgets",
    "operating_expenses",
    "rent_charges",
    "security_deposits",
    "residents",
    "resident_leases",
    "resident_payment_methods",
    "client_portal_accounts",
    "client_portal_change_requests",
    "rental_units",
)

_PREDICATE = """
(
    current_setting('app.rls_bypass', true) = 'on'
    OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
)
"""


def _policy_name(table: str) -> str:
    return f"{table}_org_isolation"


def _enable_strict_rls(table: str) -> None:
    policy = _policy_name(table)
    op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{policy}" ON "{table}" '
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def upgrade() -> None:
    for table in PROTECTED_TABLES:
        _enable_strict_rls(table)


def downgrade() -> None:
    for table in reversed(PROTECTED_TABLES):
        op.execute(f'DROP POLICY IF EXISTS "{_policy_name(table)}" ON "{table}"')
        if table == "leases":
            # Restore the revision-090 pilot semantics exactly.
            op.execute(
                """
                CREATE POLICY leases_org_isolation ON leases
                USING (
                    current_setting('app.current_org', true) IS NULL
                    OR current_setting('app.current_org', true) = ''
                    OR organization_id = current_setting('app.current_org', true)::uuid
                )
                """
            )
        else:
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
import ast
from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "118_extend_high_risk_rls.py"
)


def _migration_source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _protected_tables() -> tuple[str, ...]:
    module = ast.parse(_migration_source())
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PROTECTED_TABLES" for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


def _upgrade_predicate() -> str:
    module = ast.parse(_migration_source())
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_PREDICATE" for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


def test_high_risk_direct_org_tables_are_explicitly_covered() -> None:
    tables = set(_protected_tables())
    assert {
        "customer_invoices",
        "customer_receipts",
        "vendor_bills",
        "vendor_payments",
        "gl_accounts",
        "journal_entries",
        "bank_accounts",
        "bank_transactions",
        "residents",
        "resident_leases",
        "resident_payment_methods",
        "client_portal_accounts",
        "client_portal_change_requests",
    } <= tables
    assert not {
        "customer_invoice_lines",
        "vendor_bill_lines",
        "journal_entry_lines",
        "resident_lease_occupants",
    } & tables


def test_policy_is_fail_closed_and_has_explicit_bypass() -> None:
    source = _migration_source()
    predicate = _upgrade_predicate()
    assert "app.rls_bypass" in predicate
    assert "app.current_org" in predicate
    assert "NULLIF(current_setting('app.current_org', true), '')::uuid" in predicate
    assert "IS NULL" not in predicate
    assert "WITH CHECK" in source
    assert "FORCE ROW LEVEL SECURITY" in source

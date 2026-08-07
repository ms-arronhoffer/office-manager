"""Fixture-free regression tests for resident ACH migration policy ownership."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "122_add_resident_ach_payments.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_122", _MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_payment_method_policy_is_replaced_before_create():
    migration = _load_migration()
    operations = MagicMock()

    with patch.object(migration, "op", operations):
        migration._enable_rls("resident_payment_methods")

    statements = [call.args[0] for call in operations.execute.call_args_list]
    assert statements[0] == (
        'DROP POLICY IF EXISTS "resident_payment_methods_org_isolation" '
        'ON "resident_payment_methods"'
    )
    assert statements[-1].startswith(
        "CREATE POLICY resident_payment_methods_org_isolation"
    )


def test_downgrade_preserves_policy_owned_by_migration_118():
    migration = _load_migration()
    operations = MagicMock()

    with patch.object(migration, "op", operations):
        migration.downgrade()

    statements = [call.args[0] for call in operations.execute.call_args_list]
    assert not any(
        "resident_payment_methods_org_isolation" in statement
        for statement in statements
    )

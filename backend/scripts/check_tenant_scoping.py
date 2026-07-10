#!/usr/bin/env python3
"""Flag router primary-key lookups that skip tenant scoping."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROUTERS_DIR = BACKEND_DIR / "app" / "routers"
EXCLUDED_PARTS = {"admin"}
NON_ORG_MODEL_NAMES = {
    "Attachment",
    "LandlordContact",
    "LeaseNote",
    "LeaseOption",
    "LeaseRenewal",
    "Notification",
    "OfficeTransition",
    "Organization",
    "OwnerProperty",
    "ReportSchedule",
    "SpaceHistory",
    "TicketNote",
    "TransitionChecklistItem",
    "User",
    "WorkOrderCostLine",
}
ALLOWLIST: dict[tuple[str, int], str] = {}
FUNCTION_ALLOWLIST: dict[str, str] = {}


@dataclass
class Violation:
    relpath: str
    line: int
    function_name: str | None
    snippet: str


def _attr_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _where_chain(call: ast.Call) -> tuple[list[ast.AST], ast.AST]:
    clauses: list[ast.AST] = []
    current: ast.AST = call
    while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute) and current.func.attr == "where":
        clauses.extend(current.args)
        current = current.func.value
    return clauses, current


def _find_select_model(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
        current = current.func.value
    if not isinstance(current, ast.Call):
        return None
    if not isinstance(current.func, ast.Name) or current.func.id != "select" or not current.args:
        return None
    first = current.args[0]
    chain = _attr_chain(first)
    if not chain:
        return None
    return chain[-1]


def _contains_model_id_compare(expr: ast.AST, model_name: str) -> bool:
    for node in ast.walk(expr):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
            continue
        left_chain = _attr_chain(node.left)
        right = node.comparators[0]
        right_chain = _attr_chain(right)
        if left_chain == [model_name, "id"] and not isinstance(right, ast.Attribute):
            return True
        if right_chain == [model_name, "id"] and not isinstance(node.left, ast.Attribute):
            return True
    return False


def _contains_org_reference(expr: ast.AST, model_name: str) -> bool:
    for node in ast.walk(expr):
        chain = _attr_chain(node)
        if chain[:1] != [model_name]:
            continue
        if any(part in {"organization_id", "organization", "org_id"} for part in chain[1:]):
            return True
    return False


def _contains_parent_scope(expr: ast.AST, model_name: str) -> bool:
    for node in ast.walk(expr):
        chain = _attr_chain(node)
        if chain[:1] != [model_name] or len(chain) != 2:
            continue
        attr = chain[1]
        if attr != "id" and (attr.endswith("_id") or attr == "entity_id"):
            return True
    return False


def _enclosing_function(tree: ast.AST, target: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(child is target for child in ast.walk(node)):
                return node.name
    return None


def _scan_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations: list[Violation] = []
    relpath = path.relative_to(BACKEND_DIR).as_posix()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "where":
            continue

        clauses, base = _where_chain(node)
        model_name = _find_select_model(base)
        if not model_name or model_name in NON_ORG_MODEL_NAMES:
            continue

        if not any(_contains_model_id_compare(clause, model_name) for clause in clauses):
            continue
        if any(_contains_org_reference(clause, model_name) for clause in clauses):
            continue
        if any(_contains_parent_scope(clause, model_name) for clause in clauses):
            continue

        function_name = _enclosing_function(tree, node)
        if function_name and function_name in FUNCTION_ALLOWLIST:
            continue
        if (relpath, node.lineno) in ALLOWLIST:
            continue

        violations.append(
            Violation(
                relpath=relpath,
                line=node.lineno,
                function_name=function_name,
                snippet=(ast.get_source_segment(source, node) or source.splitlines()[node.lineno - 1]).strip(),
            )
        )
    return violations


def main() -> int:
    violations: list[Violation] = []
    for path in sorted(ROUTERS_DIR.rglob("*.py")):
        if any(part in EXCLUDED_PARTS for part in path.relative_to(ROUTERS_DIR).parts):
            continue
        violations.extend(_scan_file(path))

    if not violations:
        print("tenant scoping lint: OK")
        return 0

    print("tenant scoping lint: found unscoped primary-key lookups", file=sys.stderr)
    for violation in violations:
        print(
            f"{violation.relpath}:{violation.line}: "
            f"{violation.function_name or '<module>'}: {violation.snippet}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

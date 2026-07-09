"""Structured natural-language data query engine.

This module lets the assistant answer precise, aggregate, and relational
questions about *any* organization-scoped table ("how many open residential
applications", "total rent charged this month", "which vendors are in TX") by
mapping a natural-language request onto a **validated, constrained query spec**
that is executed by the ORM. It never generates or runs free-form SQL.

The design mirrors the codebase's established safe pattern
(:func:`app.services.report_service.validate_report_spec` and
``ai_service.build_report_spec``): the model only ever sees an allow-listed
catalog of entities/columns, and every field of the resulting spec is validated
against that catalog before a single, read-only ``SELECT`` is built. All queries
are explicitly scoped to the caller's ``organization_id``.

Two layers live here:

* the **catalog** (:func:`build_catalog`, :func:`catalog_for_prompt`) reflecting
  every org-scoped model into a safe entity/column allow-list, reusing the
  sensitive-column and skip-table policy from
  :mod:`app.services.knowledge_service`; and
* the **executor** (:func:`validate_spec`, :func:`execute_spec`) that validates a
  raw spec and runs it, returning ``{columns, rows, total}``.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import String, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.base import Base

# Import the model package so every ORM class is registered on ``Base.registry``
# before we reflect over it to build the catalog.
import app.models  # noqa: F401

from app.services.knowledge_service import (
    _GENERIC_SKIP_TABLES,
    _humanize,
    _is_sensitive_column,
)


class DataQueryError(ValueError):
    """Raised when a query spec is invalid for the catalog."""


# ── Policy ────────────────────────────────────────────────────────────────────

# Tables that are org-scoped but must never be exposed to the data-query engine:
# credential/secret stores, the embedding indexes, and internal metering/audit
# noise. We reuse knowledge_service's skip list (which already covers users,
# api_keys, tokens-bearing tables, billing, usage, activity/email logs, and the
# vector indexes) and add the assistant's own bookkeeping tables.
_SKIP_TABLES = frozenset(_GENERIC_SKIP_TABLES) | frozenset({
    "client_portal_change_requests", "lease_signature_requests",
    "email_acknowledgements", "support_requests", "notifications",
})

# Columns that carry no answerable business meaning or are bookkeeping-only.
# ``organization_id`` is intentionally excluded from the catalog: the engine
# always applies the org filter itself, so the model never needs to reference it.
_SKIP_COLUMNS = frozenset({
    "organization_id", "embedding", "search_vector",
})

# Aggregate functions the engine can compute. ``count`` needs no column;
# the rest require a numeric ``aggregate_column``.
_AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})
_NUMERIC_AGGREGATES = frozenset({"sum", "avg", "min", "max"})

# Comparison operators the engine understands, mapped to their arity.
# ``in`` takes a list; ``is_null``/``not_null`` take no value.
_OPERATORS = frozenset({
    "eq", "ne", "gt", "gte", "lt", "lte",
    "contains", "starts_with", "in", "is_null", "not_null",
})
_NO_VALUE_OPERATORS = frozenset({"is_null", "not_null"})
# Operators that only make sense on text columns.
_TEXT_OPERATORS = frozenset({"contains", "starts_with"})

# Hard caps so a single request can never exhaust the database or the response.
MAX_LIMIT = 500
DEFAULT_LIMIT = 100

_CATALOG_CACHE: dict[str, dict[str, Any]] | None = None


# ── Catalog ───────────────────────────────────────────────────────────────────

def _python_type(column) -> type:
    """Best-effort Python type for a column, defaulting to ``str``."""
    try:
        return column.type.python_type
    except (NotImplementedError, AttributeError):
        return str


def _kind_for_type(py_type: type) -> str:
    """Classify a Python type into a coarse catalog "kind" for prompting."""
    if py_type is bool:
        return "boolean"
    if py_type in (int,):
        return "integer"
    if py_type in (float, Decimal):
        return "number"
    if py_type in (_dt.datetime,):
        return "datetime"
    if py_type in (_dt.date,):
        return "date"
    if py_type is uuid.UUID:
        return "id"
    return "text"


def build_catalog() -> dict[str, dict[str, Any]]:
    """Reflect every queryable org-scoped model into a safe entity catalog.

    Returns a mapping ``{entity: {model, title, columns: {name: {...}}}}`` where
    each entity is an organization-scoped table with a single UUID ``id`` primary
    key, excluding the sensitive/low-signal skip tables. Sensitive columns
    (passwords, tokens, hashes, …) are dropped so they can neither be selected,
    filtered on, nor returned. The result is cached per process.
    """
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    catalog: dict[str, dict[str, Any]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = getattr(cls, "__tablename__", None)
        if not table or table in _SKIP_TABLES:
            continue
        column_keys = {col.key for col in mapper.columns}
        if "organization_id" not in column_keys:
            continue
        primary_key = list(mapper.primary_key)
        if len(primary_key) != 1 or primary_key[0].key != "id":
            continue

        columns: dict[str, dict[str, Any]] = {}
        for col in mapper.columns:
            key = col.key
            if key in _SKIP_COLUMNS or _is_sensitive_column(key):
                continue
            py_type = _python_type(col)
            columns[key] = {
                "label": _humanize(key),
                "kind": _kind_for_type(py_type),
                "python_type": py_type,
            }
        if not columns:
            continue
        catalog[table] = {
            "model": cls,
            "title": _humanize(table),
            "columns": columns,
        }

    _CATALOG_CACHE = dict(sorted(catalog.items()))
    return _CATALOG_CACHE


def catalog_for_prompt() -> list[dict[str, Any]]:
    """Serialise the catalog into a compact, model-safe description.

    Only entity/column names, labels, and kinds are exposed — never the ORM
    classes — so this can be safely embedded in an AI prompt. Sorted for
    deterministic output.
    """
    catalog = build_catalog()
    entities = []
    for entity, cfg in catalog.items():
        entities.append({
            "entity": entity,
            "title": cfg["title"],
            "columns": [
                {"name": name, "label": meta["label"], "kind": meta["kind"]}
                for name, meta in cfg["columns"].items()
            ],
        })
    return entities


# ── Value coercion ────────────────────────────────────────────────────────────

def _coerce_scalar(value: Any, py_type: type, column: str) -> Any:
    """Coerce a raw spec value to the column's Python type.

    Raises :class:`DataQueryError` when the value cannot be represented as the
    column's type (e.g. a non-numeric string for an integer column).
    """
    if value is None:
        return None
    try:
        if py_type is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes", "y", "t")
        if py_type is int:
            return int(value)
        if py_type is float:
            return float(value)
        if py_type is Decimal:
            return Decimal(str(value))
        if py_type is uuid.UUID:
            return uuid.UUID(str(value))
        if py_type is _dt.datetime:
            return _dt.datetime.fromisoformat(str(value))
        if py_type is _dt.date:
            return _dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise DataQueryError(
            f"Value {value!r} is not valid for column '{column}'."
        ) from exc
    return str(value)


# ── Validation ────────────────────────────────────────────────────────────────

def _require_column(entity_cfg: dict[str, Any], entity: str, name: str) -> dict:
    meta = entity_cfg["columns"].get(name)
    if meta is None:
        raise DataQueryError(
            f"Unknown column '{name}' for entity '{entity}'."
        )
    return meta


def validate_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw query spec against the catalog, returning a clean spec.

    Every entity, column, operator, and aggregate is checked against the
    allow-list; anything unknown raises :class:`DataQueryError` so the caller can
    surface a clean 422. Filter values are coerced to their column's type.
    """
    if not isinstance(raw, dict):
        raise DataQueryError("Query spec must be an object.")

    catalog = build_catalog()
    entity = str(raw.get("entity") or "").strip()
    entity_cfg = catalog.get(entity)
    if entity_cfg is None:
        raise DataQueryError(f"Unknown entity: {entity!r}.")

    # select ---------------------------------------------------------------
    raw_select = raw.get("select")
    select_cols: list[str] = []
    if isinstance(raw_select, list):
        for name in raw_select:
            name = str(name).strip()
            _require_column(entity_cfg, entity, name)
            if name not in select_cols:
                select_cols.append(name)

    # aggregate ------------------------------------------------------------
    aggregate = raw.get("aggregate")
    aggregate = str(aggregate).strip().lower() if aggregate else None
    if aggregate is not None and aggregate not in _AGGREGATES:
        raise DataQueryError(f"Unknown aggregate: {aggregate!r}.")
    aggregate_column = raw.get("aggregate_column")
    aggregate_column = str(aggregate_column).strip() if aggregate_column else None
    if aggregate in _NUMERIC_AGGREGATES:
        if not aggregate_column:
            raise DataQueryError(
                f"Aggregate '{aggregate}' requires an aggregate_column."
            )
        meta = _require_column(entity_cfg, entity, aggregate_column)
        if meta["kind"] not in ("integer", "number"):
            raise DataQueryError(
                f"Aggregate '{aggregate}' needs a numeric column, "
                f"but '{aggregate_column}' is {meta['kind']}."
            )
    elif aggregate == "count":
        aggregate_column = None

    # group_by -------------------------------------------------------------
    raw_group = raw.get("group_by")
    group_by: list[str] = []
    if isinstance(raw_group, list):
        for name in raw_group:
            name = str(name).strip()
            _require_column(entity_cfg, entity, name)
            if name not in group_by:
                group_by.append(name)
    if group_by and aggregate is None:
        raise DataQueryError("group_by requires an aggregate.")

    # filters --------------------------------------------------------------
    raw_filters = raw.get("filters")
    filters: list[dict[str, Any]] = []
    if isinstance(raw_filters, list):
        for f in raw_filters:
            if not isinstance(f, dict):
                raise DataQueryError("Each filter must be an object.")
            col = str(f.get("column") or "").strip()
            op = str(f.get("op") or "").strip().lower()
            meta = _require_column(entity_cfg, entity, col)
            if op not in _OPERATORS:
                raise DataQueryError(f"Unknown operator: {op!r}.")
            if op in _TEXT_OPERATORS and meta["kind"] not in ("text",):
                raise DataQueryError(
                    f"Operator '{op}' only applies to text columns, "
                    f"but '{col}' is {meta['kind']}."
                )
            entry: dict[str, Any] = {"column": col, "op": op}
            if op not in _NO_VALUE_OPERATORS:
                value = f.get("value")
                if op == "in":
                    if not isinstance(value, list) or not value:
                        raise DataQueryError(
                            f"Operator 'in' requires a non-empty list for '{col}'."
                        )
                    entry["value"] = [
                        _coerce_scalar(v, meta["python_type"], col) for v in value
                    ]
                elif op in _TEXT_OPERATORS:
                    entry["value"] = str(value if value is not None else "")
                else:
                    entry["value"] = _coerce_scalar(value, meta["python_type"], col)
            filters.append(entry)

    # order_by -------------------------------------------------------------
    order_by = None
    raw_order = raw.get("order_by")
    if isinstance(raw_order, dict):
        col = str(raw_order.get("column") or "").strip()
        if col:
            _require_column(entity_cfg, entity, col)
            direction = str(raw_order.get("direction") or "asc").strip().lower()
            direction = "desc" if direction == "desc" else "asc"
            order_by = {"column": col, "direction": direction}

    # limit ----------------------------------------------------------------
    try:
        limit = int(raw.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    return {
        "entity": entity,
        "select": select_cols,
        "filters": filters,
        "aggregate": aggregate,
        "aggregate_column": aggregate_column,
        "group_by": group_by,
        "order_by": order_by,
        "limit": limit,
    }


# ── Execution ─────────────────────────────────────────────────────────────────

def _column_attr(model, name: str) -> InstrumentedAttribute:
    return getattr(model, name)


def _build_condition(model, f: dict[str, Any]):
    col = _column_attr(model, f["column"])
    op = f["op"]
    if op == "is_null":
        return col.is_(None)
    if op == "not_null":
        return col.isnot(None)
    value = f.get("value")
    if op == "eq":
        return col == value
    if op == "ne":
        return col != value
    if op == "gt":
        return col > value
    if op == "gte":
        return col >= value
    if op == "lt":
        return col < value
    if op == "lte":
        return col <= value
    if op == "in":
        return col.in_(value)
    if op == "contains":
        return col.cast(String).ilike(f"%{value}%")
    if op == "starts_with":
        return col.cast(String).ilike(f"{value}%")
    raise DataQueryError(f"Unsupported operator: {op!r}.")


def _serialize(value: Any) -> Any:
    """Render a cell value as a JSON-friendly primitive."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


async def execute_spec(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Execute a validated spec, returning ``{columns, rows, total}``.

    The query is always filtered to ``organization_id`` and soft-deleted rows
    are excluded when the model supports them. Nothing is mutated; only a single
    read-only ``SELECT`` is issued.
    """
    catalog = build_catalog()
    entity_cfg = catalog[spec["entity"]]
    model = entity_cfg["model"]

    # Explicit, non-negotiable organization scope — never trust the spec for it.
    conditions = [model.organization_id == organization_id]
    if hasattr(model, "is_deleted"):
        conditions.append(model.is_deleted == False)  # noqa: E712
    for f in spec["filters"]:
        conditions.append(_build_condition(model, f))
    where_clause = and_(*conditions)

    aggregate = spec["aggregate"]
    if aggregate:
        return await _execute_aggregate(db, model, spec, where_clause)
    return await _execute_rows(db, model, entity_cfg, spec, where_clause)


def _agg_func(aggregate: str, col=None):
    if aggregate == "count":
        return func.count()
    return getattr(func, aggregate)(col)


async def _execute_aggregate(db, model, spec, where_clause) -> dict[str, Any]:
    aggregate = spec["aggregate"]
    agg_col = (
        _column_attr(model, spec["aggregate_column"])
        if spec["aggregate_column"]
        else None
    )
    agg_expr = _agg_func(aggregate, agg_col).label("value")
    agg_label = (
        f"{aggregate}({spec['aggregate_column']})"
        if spec["aggregate_column"]
        else "count"
    )

    if spec["group_by"]:
        group_attrs = [_column_attr(model, g) for g in spec["group_by"]]
        stmt = (
            select(*group_attrs, agg_expr)
            .where(where_clause)
            .group_by(*group_attrs)
        )
        # Ordering: honour explicit order_by, else sort by the aggregate desc.
        order_by = spec["order_by"]
        if order_by and order_by["column"] in spec["group_by"]:
            col = _column_attr(model, order_by["column"])
            stmt = stmt.order_by(col.desc() if order_by["direction"] == "desc" else col.asc())
        else:
            stmt = stmt.order_by(agg_expr.desc())
        stmt = stmt.limit(spec["limit"])
        result = await db.execute(stmt)
        columns = list(spec["group_by"]) + [agg_label]
        rows = [
            [_serialize(v) for v in row]
            for row in result.all()
        ]
        return {"columns": columns, "rows": rows, "total": len(rows)}

    stmt = select(agg_expr).where(where_clause)
    result = await db.execute(stmt)
    value = result.scalar_one()
    value = _serialize(value if value is not None else 0)
    return {"columns": [agg_label], "rows": [[value]], "total": 1}


async def _execute_rows(db, model, entity_cfg, spec, where_clause) -> dict[str, Any]:
    select_cols = spec["select"] or list(entity_cfg["columns"].keys())
    attrs = [_column_attr(model, c) for c in select_cols]

    stmt = select(*attrs).where(where_clause)
    order_by = spec["order_by"]
    if order_by:
        col = _column_attr(model, order_by["column"])
        stmt = stmt.order_by(col.desc() if order_by["direction"] == "desc" else col.asc())
    stmt = stmt.limit(spec["limit"])

    result = await db.execute(stmt)
    rows = [[_serialize(v) for v in row] for row in result.all()]

    # Total (unbounded) count so callers can tell when results were truncated.
    count_stmt = select(func.count()).select_from(model).where(where_clause)
    total = (await db.execute(count_stmt)).scalar_one()

    return {"columns": select_cols, "rows": rows, "total": int(total)}


def summarize(spec: dict[str, Any], result: dict[str, Any]) -> str:
    """Produce a short deterministic answer when AI narration is unavailable.

    Used as the graceful-degradation fallback so ``/ai/data/query`` still returns
    a useful plain-English answer with the model unconfigured.
    """
    entity = build_catalog()[spec["entity"]]["title"]
    aggregate = spec["aggregate"]
    if aggregate and not spec["group_by"]:
        value = result["rows"][0][0] if result["rows"] else 0
        if aggregate == "count":
            return f"{value} {entity.lower()} match your query."
        return f"{aggregate.upper()} of {spec['aggregate_column']} for {entity.lower()}: {value}."
    if aggregate and spec["group_by"]:
        return (
            f"{result['total']} grouped result(s) for {entity.lower()} "
            f"by {', '.join(spec['group_by'])}."
        )
    shown = len(result["rows"])
    total = result["total"]
    if total > shown:
        return f"Showing {shown} of {total} {entity.lower()} matching your query."
    return f"{total} {entity.lower()} match your query."

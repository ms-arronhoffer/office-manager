from sqlalchemy import asc, desc
from sqlalchemy.sql import Select


def apply_sorting(
    stmt: Select,
    sort_by: str | None,
    sort_order: str,
    allowed_columns: dict,
    defaults: list,
) -> Select:
    """Apply validated sorting to a SQLAlchemy select statement.

    Args:
        stmt: The base select statement.
        sort_by: Column name to sort by (from query param).
        sort_order: "asc" or "desc".
        allowed_columns: Mapping of param name -> SQLAlchemy column.
        defaults: Fallback order_by clauses when sort_by is None/invalid.
    """
    direction = desc if sort_order == "desc" else asc

    if sort_by and sort_by in allowed_columns:
        return stmt.order_by(direction(allowed_columns[sort_by]))

    # Fall back to defaults
    return stmt.order_by(*defaults)

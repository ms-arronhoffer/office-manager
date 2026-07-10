"""Mandated tenant-scoping helpers for per-organization lookups.

Use :func:`load_or_404` / :func:`scoped` for any organization-scoped primary-key
lookup in routers. Writing a bare ``select(Model).where(Model.id == ...)``
without an organization filter is forbidden and CI lint will flag it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.sql import Select


def _org_scope_clause(model: type[Any], org_id: Any, org_attr: str = "organization_id"):
    candidates = [org_attr]
    for candidate in ("organization_id", "org_id", "organization"):
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        if not hasattr(model, candidate):
            continue
        attr = getattr(model, candidate)
        if candidate == "organization":
            return attr.has(id=org_id)
        return attr == org_id

    raise AttributeError(
        f"{model.__name__} does not expose an organization scope attribute "
        f"(tried: {', '.join(candidates)})"
    )


def scoped(stmt: Select | None, model: type[Any], org_id: Any) -> Select:
    """Apply the model's tenant filter to ``stmt`` or a fresh ``select(model)``."""

    return (stmt or select(model)).where(_org_scope_clause(model, org_id))


async def load_or_404(
    db,
    model: type[Any],
    id_,
    org_id,
    *,
    id_attr: str = "id",
    org_attr: str = "organization_id",
    extra_filters: Iterable[Any] | None = None,
    detail: str | None = None,
):
    """Load one tenant-scoped row by primary key or raise a 404."""

    stmt = select(model).where(getattr(model, id_attr) == id_)
    stmt = stmt.where(_org_scope_clause(model, org_id, org_attr))
    if extra_filters:
        stmt = stmt.where(*extra_filters)
    result = await db.execute(stmt)
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{model.__name__} not found",
        )
    return instance

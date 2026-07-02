"""Inspection service layer (Phase 1.5).

Holds the inspection rules that keep the router thin: snapshotting a template's
items onto a new inspection, and computing an inspection's overall pass/fail
result from its recorded item results.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inspection import (
    INSPECTION_RESULTS,
    Inspection,
    InspectionItemResult,
    InspectionTemplate,
)


class InspectionError(ValueError):
    """Raised for inspection rule violations."""


def validate_result(value: str | None) -> str | None:
    """Ensure a per-item result is one of the allowed outcomes (or None)."""
    if value is None:
        return None
    if value not in INSPECTION_RESULTS:
        raise InspectionError(
            f"result must be one of: {', '.join(sorted(INSPECTION_RESULTS))}."
        )
    return value


def snapshot_items(template: InspectionTemplate) -> list[InspectionItemResult]:
    """Create blank item-results from a template's items, preserving order."""
    return [
        InspectionItemResult(
            template_item_id=item.id,
            label=item.label,
            sort_order=item.sort_order,
            is_required=item.is_required,
            result=None,
        )
        for item in template.items
    ]


def compute_overall_result(inspection: Inspection) -> str:
    """Derive an inspection's overall result from its item results.

    - ``fail`` if any required item failed.
    - ``na`` if every item is n/a or unset.
    - ``pass`` otherwise (all required items passed).
    """
    any_pass = False
    for item in inspection.results:
        if item.is_required and item.result == "fail":
            return "fail"
        if item.result == "pass":
            any_pass = True
    return "pass" if any_pass else "na"


def required_items_scored(inspection: Inspection) -> bool:
    """True when every required item has a recorded result."""
    return all(
        item.result in INSPECTION_RESULTS
        for item in inspection.results
        if item.is_required
    )


async def get_template(
    db: AsyncSession, template_id: uuid.UUID, organization_id: uuid.UUID | None
) -> InspectionTemplate | None:
    return (
        await db.execute(
            select(InspectionTemplate)
            .where(
                InspectionTemplate.id == template_id,
                InspectionTemplate.organization_id == organization_id,
            )
            .options(selectinload(InspectionTemplate.items))
        )
    ).scalar_one_or_none()


async def get_inspection(
    db: AsyncSession, inspection_id: uuid.UUID, organization_id: uuid.UUID | None
) -> Inspection | None:
    return (
        await db.execute(
            select(Inspection)
            .where(
                Inspection.id == inspection_id,
                Inspection.organization_id == organization_id,
            )
            .options(selectinload(Inspection.results))
        )
    ).scalar_one_or_none()

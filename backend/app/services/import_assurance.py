"""Assurance around bulk loads and system migrations.

Provides the two things a buyer asks for when their data is moved into a new
system: *did it all arrive*, and *can I prove it*.

* :func:`check_replay` refuses an upload whose bytes have already been applied,
  so a re-sent spreadsheet cannot double-post.
* :func:`record_batch` writes an auditable record of every load, including the
  individual rows that failed.
* :func:`build_tie_out` compares source counts against what actually landed in
  each table and reports a per-entity variance, which is the cutover evidence a
  finance team signs off against.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_batch import ImportBatch, content_fingerprint
from app.models.landlord import Landlord
from app.models.lease import Lease
from app.models.office import Office
from app.models.resident import RentalUnit, Resident
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill

# Tables a migrated entity lands in, used to count what actually arrived.
_ENTITY_TARGETS = {
    "properties": Office,
    "offices": Office,
    "units": RentalUnit,
    "leases": Lease,
    "tenants": Resident,
    "residents": Resident,
    "vendors": Vendor,
    "landlords": Landlord,
    "bills": VendorBill,
}


class ReplayDetected(Exception):
    """Raised when an identical import payload has already been applied."""

    def __init__(self, batch: ImportBatch):
        self.batch = batch
        super().__init__(
            "This exact file has already been imported "
            f"on {batch.created_at:%Y-%m-%d %H:%M} UTC "
            f"({batch.created_count} created, {batch.updated_count} updated). "
            "Re-importing it would duplicate that work."
        )


async def check_replay(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    entity_type: str,
    payload: bytes,
) -> str:
    """Return the payload fingerprint, raising if it was already applied."""
    fingerprint = content_fingerprint(entity_type, payload)
    prior = (
        await db.execute(
            select(ImportBatch)
            .where(
                ImportBatch.organization_id == organization_id,
                ImportBatch.content_hash == fingerprint,
                ImportBatch.status.in_(("completed", "completed_with_errors")),
            )
            .order_by(ImportBatch.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if prior is not None:
        raise ReplayDetected(prior)
    return fingerprint


async def record_batch(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    source: str,
    entity_type: str,
    fingerprint: str,
    file_name: str | None,
    created: int,
    updated: int,
    skipped: int,
    errors: list,
    imported_by_id: uuid.UUID | None = None,
    status: str | None = None,
) -> ImportBatch:
    """Persist the outcome of a load so it can be audited and explained."""
    batch = ImportBatch(
        organization_id=organization_id,
        source=source,
        entity_type=entity_type,
        file_name=file_name,
        content_hash=fingerprint,
        status=status
        or ("completed_with_errors" if errors else "completed"),
        rows_total=created + updated + skipped,
        created_count=created,
        updated_count=updated,
        skipped_count=skipped,
        error_count=len(errors),
        row_errors=[str(e) for e in errors][:500],
        imported_by_id=imported_by_id,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def _count(db: AsyncSession, model, organization_id) -> int:
    stmt = select(func.count()).select_from(model)
    if hasattr(model, "organization_id"):
        stmt = stmt.where(model.organization_id == organization_id)
    if hasattr(model, "is_deleted"):
        stmt = stmt.where(model.is_deleted.is_(False))
    return (await db.execute(stmt)).scalar_one()


async def build_tie_out(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    source_counts: dict[str, int],
) -> dict:
    """Compare what the source system reported against what actually landed.

    ``source_counts`` maps entity name to the number of records the source
    system said it had. The result reports the destination count and variance
    per entity, and only reports ``balanced`` when nothing is missing.
    """
    entities = []
    balanced = True
    for entity, expected in sorted(source_counts.items()):
        model = _ENTITY_TARGETS.get(entity)
        if model is None:
            entities.append(
                {
                    "entity": entity,
                    "source_count": expected,
                    "destination_count": None,
                    "variance": None,
                    "status": "not_verifiable",
                }
            )
            continue
        actual = await _count(db, model, organization_id)
        variance = actual - int(expected or 0)
        if variance != 0:
            balanced = False
        entities.append(
            {
                "entity": entity,
                "source_count": int(expected or 0),
                "destination_count": actual,
                "variance": variance,
                "status": "balanced" if variance == 0 else "variance",
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc),
        "balanced": balanced,
        "entities": entities,
    }

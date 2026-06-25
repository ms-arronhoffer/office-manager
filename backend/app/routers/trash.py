"""
Admin "trash" router — lists soft-deleted records across all top-level entities.

Entities each retain their own dedicated `PATCH /{entity}/{id}/restore` endpoint;
this router only provides read access so an admin UI can browse and pick records
to restore.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.hvac_contract import HvacContract
from app.models.landlord import Landlord
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.office import Office
from app.models.transition import OfficeTransition
from app.models.user import User
from app.models.vendor import Vendor

router = APIRouter()

# Map entity_type -> (Model class, label_attribute_name).
# label_attribute_name is the column we display as a human-readable name.
ENTITY_CONFIG: dict[str, tuple[Any, str]] = {
    "office": (Office, "location_name"),
    "lease": (Lease, "lease_name"),
    "landlord": (Landlord, "contact_name"),
    "vendor": (Vendor, "company_name"),
    "transition": (OfficeTransition, "address"),
    "hvac_contract": (HvacContract, "hvac_company"),
    "maintenance_ticket": (MaintenanceTicket, "title"),
}


@router.get("")
async def list_trash(
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """
    List soft-deleted records.

    If `entity_type` is omitted, returns counts only for each type
    (cheap overview). With `entity_type`, returns the actual rows.
    """
    if entity_type is None:
        counts: dict[str, int] = {}
        for et, (Model, _label) in ENTITY_CONFIG.items():
            stmt = select(Model.id).where(Model.is_deleted.is_(True))
            res = await db.execute(stmt)
            counts[et] = len(res.scalars().all())
        return {"counts": counts, "supported_types": list(ENTITY_CONFIG.keys())}

    if entity_type not in ENTITY_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type: {entity_type}")

    Model, label_attr = ENTITY_CONFIG[entity_type]
    stmt = (
        select(Model)
        .where(Model.is_deleted.is_(True))
        .order_by(Model.deleted_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()

    items = []
    for row in rows:
        items.append(
            {
                "id": str(row.id),
                "entity_type": entity_type,
                "label": getattr(row, label_attr, None) or str(row.id),
                "deleted_at": row.deleted_at.isoformat() if getattr(row, "deleted_at", None) else None,
            }
        )
    return {"entity_type": entity_type, "items": items}


@router.delete("/{entity_type}/{entity_id}/permanent")
async def permanent_delete(
    entity_type: str,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """
    Hard-delete a soft-deleted record. Use with care — there is no undo.
    """
    if entity_type not in ENTITY_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type: {entity_type}")
    Model, _label = ENTITY_CONFIG[entity_type]

    res = await db.execute(
        select(Model).where(Model.id == entity_id, Model.is_deleted.is_(True))
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Soft-deleted record not found.")
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "entity_type": entity_type, "id": str(entity_id)}

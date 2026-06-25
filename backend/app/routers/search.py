import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.office import Office
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.landlord import Landlord
from app.models.user import User

router = APIRouter()


async def _fts_or_like(db, stmt_fts, stmt_like, limit):
    """Try full-text search; fall back to ilike if tsvector column is missing."""
    try:
        result = await db.execute(stmt_fts)
        return result.all()
    except Exception:
        result = await db.execute(stmt_like)
        return result.all()


@router.get("")
async def global_search(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    results = []
    term = f"%{q}%"

    # Offices — full-text with ilike fallback
    fts = (
        select(Office.id, Office.location_name, Office.city)
        .where(
            Office.is_deleted.is_(False),
            text("offices.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(offices.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(Office.id, Office.location_name, Office.city)
        .where(
            Office.is_deleted.is_(False),
            or_(Office.location_name.ilike(term), Office.city.ilike(term)),
        )
        .limit(limit)
    )
    for row in await _fts_or_like(db, fts, like, limit):
        results.append({
            "entity_type": "office",
            "entity_id": str(row.id),
            "label": row.location_name,
            "sublabel": row.city or "Office",
        })

    # Leases
    fts = (
        select(Lease.id, Lease.lease_name, Lease.lessor_name)
        .where(
            Lease.is_deleted.is_(False),
            text("leases.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(leases.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(Lease.id, Lease.lease_name, Lease.lessor_name)
        .where(
            Lease.is_deleted.is_(False),
            or_(Lease.lease_name.ilike(term), Lease.lessor_name.ilike(term)),
        )
        .limit(limit)
    )
    for row in await _fts_or_like(db, fts, like, limit):
        results.append({
            "entity_type": "lease",
            "entity_id": str(row.id),
            "label": row.lease_name,
            "sublabel": row.lessor_name or "Lease",
        })

    # Maintenance Tickets
    fts = (
        select(MaintenanceTicket.id, MaintenanceTicket.subject)
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            text("maintenance_tickets.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(maintenance_tickets.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(MaintenanceTicket.id, MaintenanceTicket.subject)
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.subject.ilike(term),
        )
        .limit(limit)
    )
    for row in await _fts_or_like(db, fts, like, limit):
        results.append({
            "entity_type": "maintenance_ticket",
            "entity_id": str(row.id),
            "label": row.subject,
            "sublabel": "Ticket",
        })

    # Landlords
    fts = (
        select(Landlord.id, Landlord.landlord_company, Landlord.contact_name)
        .where(
            Landlord.is_deleted.is_(False),
            text("landlords.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(landlords.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(Landlord.id, Landlord.landlord_company, Landlord.contact_name)
        .where(
            Landlord.is_deleted.is_(False),
            or_(Landlord.landlord_company.ilike(term), Landlord.contact_name.ilike(term)),
        )
        .limit(limit)
    )
    for row in await _fts_or_like(db, fts, like, limit):
        results.append({
            "entity_type": "landlord",
            "entity_id": str(row.id),
            "label": row.landlord_company or row.contact_name,
            "sublabel": row.contact_name or "Landlord",
        })

    return results[:limit]

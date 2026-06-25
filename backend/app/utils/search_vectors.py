"""Utility for maintaining PostgreSQL full-text search vectors after writes."""

import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_VECTOR_SQL = {
    "offices": (
        "UPDATE offices SET search_vector = "
        "to_tsvector('english', coalesce(location_name,'') || ' ' || coalesce(city,'') || ' ' || coalesce(notes,'')) "
        "WHERE id = :id"
    ),
    "leases": (
        "UPDATE leases SET search_vector = "
        "to_tsvector('english', coalesce(lease_name,'') || ' ' || coalesce(lessor_name,'')) "
        "WHERE id = :id"
    ),
    "maintenance_tickets": (
        "UPDATE maintenance_tickets SET search_vector = "
        "to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(description,'')) "
        "WHERE id = :id"
    ),
    "landlords": (
        "UPDATE landlords SET search_vector = "
        "to_tsvector('english', coalesce(landlord_company,'') || ' ' || coalesce(contact_name,'')) "
        "WHERE id = :id"
    ),
}


async def update_search_vector(db: AsyncSession, table: str, record_id: uuid.UUID) -> None:
    """Update the search_vector for a single record. Best-effort — caller should wrap in try/except."""
    sql = _VECTOR_SQL.get(table)
    if not sql:
        return
    await db.execute(text(sql), {"id": str(record_id)})
    await db.commit()

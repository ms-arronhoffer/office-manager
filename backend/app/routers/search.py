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
from app.models.vendor import Vendor
from app.models.management_company import ManagementCompany
from app.models.hvac_contract import HvacContract
from app.models.transition import OfficeTransition
from app.models.waiver import WaiverRequest
from app.models.user import User

router = APIRouter()

# Deep-link route prefix for each entity type. The frontend prefers the
# ``route`` returned per result, falling back to these prefixes.
ENTITY_ROUTE_PREFIXES = {
    "office": "/offices",
    "lease": "/leases",
    "maintenance_ticket": "/maintenance-tickets",
    "landlord": "/landlords",
    "vendor": "/vendors",
    "management_company": "/management-companies",
    "hvac_contract": "/hvac-contracts",
    "transition": "/transitions",
    "waiver": "/waivers",
}


def _route_for(entity_type: str, entity_id: str) -> str:
    prefix = ENTITY_ROUTE_PREFIXES.get(entity_type, "")
    # Waivers have no per-id detail page; deep-link to the list (filtered client-side).
    if entity_type == "waiver":
        return prefix
    return f"{prefix}/{entity_id}" if prefix else ""


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
    current_user: User = Depends(get_current_user),
):
    results = []
    term = f"%{q}%"
    org_id = current_user.organization_id

    # Offices — full-text with ilike fallback
    fts = (
        select(Office.id, Office.location_name, Office.city)
        .where(
            Office.is_deleted.is_(False),
            Office.organization_id == org_id,
            text("offices.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(offices.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(Office.id, Office.location_name, Office.city)
        .where(
            Office.is_deleted.is_(False),
            Office.organization_id == org_id,
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
            Lease.organization_id == org_id,
            text("leases.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(leases.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(Lease.id, Lease.lease_name, Lease.lessor_name)
        .where(
            Lease.is_deleted.is_(False),
            Lease.organization_id == org_id,
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
            MaintenanceTicket.organization_id == org_id,
            text("maintenance_tickets.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(maintenance_tickets.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(MaintenanceTicket.id, MaintenanceTicket.subject)
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.organization_id == org_id,
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
            Landlord.organization_id == org_id,
            text("landlords.search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q),
        )
        .order_by(text("ts_rank(landlords.search_vector, plainto_tsquery('english', :q)) DESC").bindparams(q=q))
        .limit(limit)
    )
    like = (
        select(Landlord.id, Landlord.landlord_company, Landlord.contact_name)
        .where(
            Landlord.is_deleted.is_(False),
            Landlord.organization_id == org_id,
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

    # Vendors — ilike only (no FTS column)
    vendor_rows = await db.execute(
        select(Vendor.id, Vendor.company_name, Vendor.contact_name)
        .where(
            Vendor.organization_id == org_id,
            or_(Vendor.company_name.ilike(term), Vendor.contact_name.ilike(term)),
        )
        .limit(limit)
    )
    for row in vendor_rows.all():
        results.append({
            "entity_type": "vendor",
            "entity_id": str(row.id),
            "label": row.company_name,
            "sublabel": row.contact_name or "Vendor",
        })

    # Management companies
    mc_rows = await db.execute(
        select(ManagementCompany.id, ManagementCompany.name, ManagementCompany.contact_name)
        .where(
            ManagementCompany.organization_id == org_id,
            or_(ManagementCompany.name.ilike(term), ManagementCompany.contact_name.ilike(term)),
        )
        .limit(limit)
    )
    for row in mc_rows.all():
        results.append({
            "entity_type": "management_company",
            "entity_id": str(row.id),
            "label": row.name,
            "sublabel": row.contact_name or "Management Company",
        })

    # HVAC contracts
    hvac_rows = await db.execute(
        select(HvacContract.id, HvacContract.hvac_company, HvacContract.office_name)
        .where(
            HvacContract.organization_id == org_id,
            or_(HvacContract.hvac_company.ilike(term), HvacContract.office_name.ilike(term)),
        )
        .limit(limit)
    )
    for row in hvac_rows.all():
        results.append({
            "entity_type": "hvac_contract",
            "entity_id": str(row.id),
            "label": row.hvac_company or row.office_name or "HVAC Contract",
            "sublabel": row.office_name or "HVAC Contract",
        })

    # Office transitions
    transition_rows = await db.execute(
        select(OfficeTransition.id, OfficeTransition.address, OfficeTransition.transition_type)
        .where(
            OfficeTransition.organization_id == org_id,
            or_(OfficeTransition.address.ilike(term), OfficeTransition.new_address.ilike(term)),
        )
        .limit(limit)
    )
    for row in transition_rows.all():
        results.append({
            "entity_type": "transition",
            "entity_id": str(row.id),
            "label": row.address or "Transition",
            "sublabel": (row.transition_type or "Transition").title(),
        })

    # Digital waiver requests
    waiver_rows = await db.execute(
        select(WaiverRequest.id, WaiverRequest.title, WaiverRequest.recipient_name)
        .where(
            WaiverRequest.organization_id == org_id,
            or_(WaiverRequest.title.ilike(term), WaiverRequest.recipient_name.ilike(term)),
        )
        .limit(limit)
    )
    for row in waiver_rows.all():
        results.append({
            "entity_type": "waiver",
            "entity_id": str(row.id),
            "label": row.title,
            "sublabel": row.recipient_name or "Waiver",
        })

    # Phase (b): attach a deep-link route to every result so the client can
    # navigate directly without re-deriving the path from the entity type.
    for r in results:
        r["route"] = _route_for(r["entity_type"], r["entity_id"])

    return results[:limit]


import math
import uuid
import csv
import io
from datetime import date, timedelta, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from icalendar import Calendar, Event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from pydantic import BaseModel
from app.models.base import _utcnow
from app.models.lease import Lease, LeaseNote
from app.models.lease_option import LeaseOption
from app.models.lease_renewal import LeaseRenewal
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.lease import (
    LeaseCreate,
    LeaseAccountingResponse,
    LeaseNoteCreate,
    LeaseNoteResponse,
    LeaseResponse,
    LeaseUpdate,
)
from app.services.activity_service import log_activity, compute_changes
from app.services.lease_accounting import compute_lease_accounting
from app.utils.search_vectors import update_search_vector
from app.utils.sorting import apply_sorting

router = APIRouter()


async def _load_lease(
    db: AsyncSession,
    lease_id: uuid.UUID,
    org_id: uuid.UUID | None,
    *,
    is_deleted: bool = False,
) -> Lease:
    """Load a lease scoped to the caller's organization, or raise 404.

    Centralizes the tenancy boundary for lease sub-resources so no endpoint can
    read or mutate another organization's lease by primary key.
    """
    result = await db.execute(
        select(Lease).where(
            Lease.id == lease_id,
            Lease.is_deleted.is_(is_deleted),
            Lease.organization_id == org_id,
        )
    )
    lease = result.scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")
    return lease


@router.get("/export")
async def export_leases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lease).options(joinedload(Lease.manager)).where(Lease.is_deleted.is_(False)).where(Lease.organization_id == current_user.organization_id).order_by(Lease.lease_expiration)
    )
    leases = result.scalars().unique().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Lease Name", "Lessor", "Expiration", "Notice Date", "Notice Given", "Manager", "Year", "Status"])
    for l in leases:
        writer.writerow([
            l.lease_name, l.lessor_name, l.lease_expiration, l.lease_notice_date,
            l.notice_given_date, l.manager.name if l.manager else "", l.expiration_year, l.status or "",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leases.csv"},
    )


@router.get("/export/ical")
async def export_leases_ical(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lease).options(joinedload(Lease.manager)).where(Lease.is_deleted.is_(False)).where(Lease.organization_id == current_user.organization_id)
    )
    leases = result.scalars().unique().all()

    cal = Calendar()
    cal.add("prodid", "-//Portfolio Desk//Leases//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", "Lease Deadlines")

    for lease in leases:
        if lease.lease_expiration:
            exp = lease.lease_expiration
            if isinstance(exp, datetime):
                exp = exp.date()
            event = Event()
            event.add("summary", f"Lease Expiring: {lease.lease_name}")
            event.add("dtstart", exp)
            event.add("dtend", exp + timedelta(days=1))
            event.add("description", f"Lessor: {lease.lessor_name or ''}")
            event["uid"] = f"lease-exp-{lease.id}@officemanager"
            cal.add_component(event)

        if lease.lease_notice_date:
            nd = lease.lease_notice_date
            if isinstance(nd, datetime):
                nd = nd.date()
            event = Event()
            event.add("summary", f"Notice Due: {lease.lease_name}")
            event.add("dtstart", nd)
            event.add("dtend", nd + timedelta(days=1))
            event.add("description", f"Lessor: {lease.lessor_name or ''}")
            event["uid"] = f"lease-notice-{lease.id}@officemanager"
            cal.add_component(event)

    return StreamingResponse(
        iter([cal.to_ical()]),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=lease-deadlines.ics"},
    )


def _apply_filters(stmt, year: int | None, manager_id: uuid.UUID | None, notice_status: str | None, status: str | None = None):
    if year is not None:
        stmt = stmt.where(Lease.expiration_year == year)
    if manager_id is not None:
        stmt = stmt.where(Lease.manager_id == manager_id)
    if status:
        stmt = stmt.where(Lease.status == status)
    if notice_status == "given":
        stmt = stmt.where(Lease.notice_given_date.is_not(None))
    elif notice_status == "not_given":
        stmt = stmt.where(Lease.notice_given_date.is_(None))
    return stmt


@router.get("/upcoming", response_model=list[LeaseResponse])
async def upcoming_leases(
    days: int = Query(default=90, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cutoff = date.today() + timedelta(days=days)
    stmt = (
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.is_deleted.is_(False))
        .where(Lease.organization_id == current_user.organization_id)
        .where(Lease.lease_expiration.is_not(None))
        .where(Lease.lease_expiration >= date.today())
        .where(Lease.lease_expiration <= cutoff)
        .order_by(Lease.lease_expiration)
    )
    result = await db.execute(stmt)
    return [LeaseResponse.model_validate(l, from_attributes=True) for l in result.scalars().unique().all()]


@router.get("/notices-due", response_model=list[LeaseResponse])
async def notices_due(
    days: int = Query(default=30, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cutoff = date.today() + timedelta(days=days)
    stmt = (
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.is_deleted.is_(False))
        .where(Lease.organization_id == current_user.organization_id)
        .where(Lease.lease_notice_date.is_not(None))
        .where(Lease.lease_notice_date >= date.today())
        .where(Lease.lease_notice_date <= cutoff)
        .where(Lease.notice_given_date.is_(None))
        .order_by(Lease.lease_notice_date)
    )
    result = await db.execute(stmt)
    return [LeaseResponse.model_validate(l, from_attributes=True) for l in result.scalars().unique().all()]


@router.get("/rent-roll")
async def rent_roll(
    region_number: int | None = Query(default=None),
    sector: str | None = Query(default=None),
    manager_id: uuid.UUID | None = Query(default=None),
    expiring_within_days: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a flattened rent roll with computed monthly/annual obligations."""
    stmt = (
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager))
        .where(Lease.is_deleted.is_(False))
        .where(Lease.organization_id == current_user.organization_id)
        .where(Lease.payment_amount.is_not(None))
    )
    if region_number is not None or sector is not None:
        from app.models.office import Office as _OfficeFilter
        stmt = stmt.join(_OfficeFilter, Lease.office_id == _OfficeFilter.id, isouter=True)
        if region_number is not None:
            stmt = stmt.where(_OfficeFilter.region_number == region_number)
        if sector is not None:
            stmt = stmt.where(_OfficeFilter.sector == sector)
    if manager_id is not None:
        stmt = stmt.where(Lease.manager_id == manager_id)
    if expiring_within_days is not None:
        cutoff = date.today() + timedelta(days=expiring_within_days)
        stmt = stmt.where(Lease.lease_expiration.is_not(None)).where(Lease.lease_expiration <= cutoff)

    stmt = stmt.order_by(Lease.lease_expiration.asc().nulls_last())
    result = await db.execute(stmt)
    leases = result.scalars().unique().all()

    rows = []
    total_monthly = 0.0
    total_annual = 0.0

    for l in leases:
        amt = float(l.payment_amount)
        freq = (l.payment_frequency or "monthly").lower()
        if freq == "monthly":
            monthly = amt
            annual = amt * 12
        elif freq == "quarterly":
            monthly = amt / 3
            annual = amt * 4
        elif freq == "annually":
            monthly = amt / 12
            annual = amt
        else:
            monthly = amt
            annual = amt * 12

        total_monthly += monthly
        total_annual += annual

        days_to_exp = None
        if l.lease_expiration:
            days_to_exp = (l.lease_expiration - date.today()).days

        rows.append({
            "lease_id": str(l.id),
            "lease_name": l.lease_name,
            "office_id": str(l.office_id) if l.office_id else None,
            "office_name": l.office.location_name if l.office else None,
            "lessor_name": l.lessor_name,
            "lease_expiration": l.lease_expiration.isoformat() if l.lease_expiration else None,
            "days_to_expiration": days_to_exp,
            "payment_amount": amt,
            "payment_frequency": freq,
            "monthly_rent": round(monthly, 2),
            "annual_rent": round(annual, 2),
            "annual_escalation_rate": float(l.annual_escalation_rate) if l.annual_escalation_rate else None,
            "lease_classification": l.lease_classification,
            "currency": l.currency or "USD",
            "manager_name": l.manager.name if l.manager else None,
        })

    return {
        "rows": rows,
        "total_monthly": round(total_monthly, 2),
        "total_annual": round(total_annual, 2),
        "count": len(rows),
    }


@router.get("", response_model=PaginatedResponse[LeaseResponse])
async def list_leases(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    year: int | None = Query(default=None),
    manager_id: uuid.UUID | None = Query(default=None),
    notice_status: str | None = Query(default=None, description="given | not_given"),
    status: str | None = Query(default=None, description="Lease lifecycle status"),
    expiring_within_days: int | None = Query(default=None, ge=1),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base_stmt = select(Lease).options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes)).where(Lease.is_deleted.is_(False))
    base_stmt = base_stmt.where(Lease.organization_id == current_user.organization_id)
    base_stmt = _apply_filters(base_stmt, year, manager_id, notice_status, status)

    if expiring_within_days is not None:
        cutoff = date.today() + timedelta(days=expiring_within_days)
        base_stmt = base_stmt.where(
            Lease.lease_expiration.is_not(None),
            Lease.lease_expiration >= date.today(),
            Lease.lease_expiration <= cutoff,
        )

    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(
        base_stmt.with_only_columns(Lease.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _LEASE_SORT_COLS = {
        "lease_name": Lease.lease_name,
        "lease_expiration": Lease.lease_expiration,
        "lessor_name": Lease.lessor_name,
        "expiration_year": Lease.expiration_year,
        "status": Lease.status,
    }
    stmt = apply_sorting(base_stmt, sort_by, sort_order, _LEASE_SORT_COLS, [Lease.lease_expiration])
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    leases = result.scalars().unique().all()

    return PaginatedResponse(
        items=[LeaseResponse.model_validate(l, from_attributes=True) for l in leases],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/{lease_id}", response_model=LeaseResponse)
async def get_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.id == lease_id, Lease.is_deleted.is_(False), Lease.organization_id == current_user.organization_id)
    )
    lease = result.unique().scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")
    return LeaseResponse.model_validate(lease, from_attributes=True)


@router.post("", response_model=LeaseResponse, status_code=status.HTTP_201_CREATED)
async def create_lease(
    payload: LeaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    lease = Lease(**payload.model_dump(), organization_id=current_user.organization_id)
    db.add(lease)
    await db.commit()
    await db.refresh(lease)

    # Build the response while the session is still healthy and BEFORE the
    # best-effort side effects below. A failure in log_activity/update_search_vector
    # leaves the async session poisoned (even after rollback, subsequent IO raises
    # MissingGreenlet), so querying afterwards would turn a successfully-committed
    # lease into a spurious 500 ("Failed to create lease").
    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.id == lease.id)
    )
    response = LeaseResponse.model_validate(result.unique().scalar_one(), from_attributes=True)

    try:
        await log_activity(db, user=current_user, action="created", entity_type="lease", entity_id=lease.id, entity_label=lease.lease_name)
    except Exception:
        pass
    try:
        await update_search_vector(db, "leases", lease.id)
    except Exception:
        pass

    return response


@router.put("/{lease_id}", response_model=LeaseResponse)
async def update_lease(
    lease_id: uuid.UUID,
    payload: LeaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(Lease).where(Lease.id == lease_id, Lease.is_deleted.is_(False), Lease.organization_id == current_user.organization_id))
    lease = result.scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    update_data = payload.model_dump(exclude_unset=True)
    old_values = {k: getattr(lease, k, None) for k in update_data}
    for field, value in update_data.items():
        if hasattr(lease, field):
            setattr(lease, field, value)

    await db.commit()
    await db.refresh(lease)

    # Build the response before the best-effort side effects below. A failure in
    # log_activity/update_search_vector poisons the async session (subsequent IO
    # raises MissingGreenlet even after rollback), so querying afterwards would
    # turn a successfully-committed update into a spurious 500 ("Failed to update
    # lease") even though the row persisted.
    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.id == lease_id, Lease.is_deleted.is_(False))
    )
    response = LeaseResponse.model_validate(result.unique().scalar_one(), from_attributes=True)

    changes = compute_changes(old_values, update_data)
    try:
        await log_activity(db, user=current_user, action="updated", entity_type="lease", entity_id=lease.id, entity_label=lease.lease_name, changes=changes)
    except Exception:
        pass
    try:
        await update_search_vector(db, "leases", lease.id)
    except Exception:
        pass

    return response


@router.delete("/{lease_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Lease).where(Lease.id == lease_id, Lease.is_deleted.is_(False), Lease.organization_id == current_user.organization_id))
    lease = result.scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")
    label = lease.lease_name
    lease.is_deleted = True
    lease.deleted_at = _utcnow()
    await db.commit()
    try:
        await log_activity(db, user=current_user, action="deleted", entity_type="lease", entity_id=lease_id, entity_label=label)
    except Exception:
        pass


@router.patch("/{lease_id}/restore", response_model=LeaseResponse)
async def restore_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(Lease).where(Lease.id == lease_id, Lease.is_deleted.is_(True), Lease.organization_id == current_user.organization_id))
    lease = result.scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found or not deleted")
    lease.is_deleted = False
    lease.deleted_at = None
    await db.commit()
    try:
        await log_activity(db, user=current_user, action="updated", entity_type="lease", entity_id=lease_id, entity_label=lease.lease_name)
    except Exception:
        pass
    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.id == lease_id, Lease.is_deleted.is_(False))
    )
    return LeaseResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.post("/{lease_id}/clone", response_model=LeaseResponse, status_code=status.HTTP_201_CREATED)
async def clone_lease(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(Lease).where(Lease.id == lease_id, Lease.is_deleted.is_(False), Lease.organization_id == current_user.organization_id))
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    new_lease = Lease(
        office_id=original.office_id,
        lease_name=f"{original.lease_name} (Renewal)",
        manager_id=original.manager_id,
        lessor_name=original.lessor_name,
        notice_period=original.notice_period,
        notice_period_days=original.notice_period_days,
        expiration_year=date.today().year,
        organization_id=current_user.organization_id,
    )
    db.add(new_lease)
    await db.commit()
    await db.refresh(new_lease)

    # Build the response before the best-effort activity log (see create_lease).
    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office), joinedload(Lease.manager), joinedload(Lease.notes))
        .where(Lease.id == new_lease.id)
    )
    response = LeaseResponse.model_validate(result.unique().scalar_one(), from_attributes=True)

    try:
        await log_activity(db, user=current_user, action="created", entity_type="lease", entity_id=new_lease.id, entity_label=new_lease.lease_name)
    except Exception:
        pass

    return response


@router.post("/{lease_id}/notes", response_model=LeaseNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_lease_note(
    lease_id: uuid.UUID,
    payload: LeaseNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)

    # Determine next order value
    from sqlalchemy import func
    order_result = await db.execute(
        select(func.coalesce(func.max(LeaseNote.note_order), 0)).where(LeaseNote.lease_id == lease_id)
    )
    next_order = order_result.scalar_one() + 1

    note = LeaseNote(
        lease_id=lease_id,
        note_text=payload.note_text,
        note_order=next_order,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return LeaseNoteResponse.model_validate(note, from_attributes=True)


@router.delete("/{lease_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lease_note(
    lease_id: uuid.UUID,
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseNote).where(LeaseNote.id == note_id, LeaseNote.lease_id == lease_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    await db.delete(note)
    await db.commit()


@router.get("/{lease_id}/accounting", response_model=LeaseAccountingResponse)
async def get_lease_accounting(
    lease_id: uuid.UUID,
    include_journal_entries: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compute ASC 842 / IFRS 16 accounting schedule for a single lease.
    Returns initial ROU asset, lease liability, amortization schedule,
    maturity analysis, and optionally journal entries.
    """
    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office))
        .where(Lease.id == lease_id, Lease.is_deleted.is_(False), Lease.organization_id == current_user.organization_id)
    )
    lease = result.unique().scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    try:
        data = compute_lease_accounting(lease, include_journal_entries=include_journal_entries)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return data


# ---------------------------------------------------------------------------
# Renewal sub-resource
# ---------------------------------------------------------------------------

class RenewalCreate(BaseModel):
    target_expiration: str | None = None
    new_rent_amount: float | None = None
    notes: str | None = None


class RenewalUpdate(BaseModel):
    status: str | None = None
    target_expiration: str | None = None
    new_rent_amount: float | None = None
    notes: str | None = None
    notice_sent_at: str | None = None
    terms_agreed_at: str | None = None
    executed_at: str | None = None


def _renewal_out(r: LeaseRenewal) -> dict:
    return {
        "id": str(r.id),
        "lease_id": str(r.lease_id),
        "status": r.status,
        "target_expiration": r.target_expiration.isoformat() if r.target_expiration else None,
        "new_rent_amount": float(r.new_rent_amount) if r.new_rent_amount is not None else None,
        "notes": r.notes,
        "notice_sent_at": r.notice_sent_at.isoformat() if r.notice_sent_at else None,
        "terms_agreed_at": r.terms_agreed_at.isoformat() if r.terms_agreed_at else None,
        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
        "created_by_id": str(r.created_by_id) if r.created_by_id else None,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


@router.post("/{lease_id}/renewals", status_code=status.HTTP_201_CREATED)
async def create_renewal(
    lease_id: uuid.UUID,
    payload: RenewalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)

    from datetime import date as _date
    renewal = LeaseRenewal(
        lease_id=lease_id,
        target_expiration=_date.fromisoformat(payload.target_expiration) if payload.target_expiration else None,
        new_rent_amount=payload.new_rent_amount,
        notes=payload.notes,
        created_by_id=current_user.id,
    )
    db.add(renewal)
    await db.commit()
    await db.refresh(renewal)
    return _renewal_out(renewal)


@router.get("/{lease_id}/renewals")
async def list_renewals(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseRenewal)
        .where(LeaseRenewal.lease_id == lease_id)
        .order_by(LeaseRenewal.created_at.desc())
    )
    return [_renewal_out(r) for r in result.scalars().all()]


@router.put("/{lease_id}/renewals/{renewal_id}")
async def update_renewal(
    lease_id: uuid.UUID,
    renewal_id: uuid.UUID,
    payload: RenewalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseRenewal).where(LeaseRenewal.id == renewal_id, LeaseRenewal.lease_id == lease_id)
    )
    renewal = result.scalar_one_or_none()
    if not renewal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Renewal not found")

    from datetime import date as _date, datetime as _dt
    if payload.status is not None:
        renewal.status = payload.status
    if payload.target_expiration is not None:
        renewal.target_expiration = _date.fromisoformat(payload.target_expiration)
    if payload.new_rent_amount is not None:
        renewal.new_rent_amount = payload.new_rent_amount
    if payload.notes is not None:
        renewal.notes = payload.notes
    if payload.notice_sent_at is not None:
        renewal.notice_sent_at = _dt.fromisoformat(payload.notice_sent_at)
    if payload.terms_agreed_at is not None:
        renewal.terms_agreed_at = _dt.fromisoformat(payload.terms_agreed_at)
    if payload.executed_at is not None:
        renewal.executed_at = _dt.fromisoformat(payload.executed_at)
    renewal.updated_at = _utcnow()

    await db.commit()
    await db.refresh(renewal)
    return _renewal_out(renewal)


@router.delete("/{lease_id}/renewals/{renewal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_renewal(
    lease_id: uuid.UUID,
    renewal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseRenewal).where(LeaseRenewal.id == renewal_id, LeaseRenewal.lease_id == lease_id)
    )
    renewal = result.scalar_one_or_none()
    if not renewal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Renewal not found")
    await db.delete(renewal)
    await db.commit()


# ---------------------------------------------------------------------------
# Lease Options sub-resource
# ---------------------------------------------------------------------------

class OptionCreate(BaseModel):
    option_type: str
    exercise_window_start: str | None = None
    exercise_window_end: str | None = None
    notice_required_days: int | None = None
    new_term_months: int | None = None
    new_rent_amount: float | None = None
    notes: str | None = None


class OptionUpdate(BaseModel):
    option_type: str | None = None
    exercise_window_start: str | None = None
    exercise_window_end: str | None = None
    notice_required_days: int | None = None
    new_term_months: int | None = None
    new_rent_amount: float | None = None
    status: str | None = None
    notes: str | None = None


def _option_out(o: LeaseOption) -> dict:
    return {
        "id": str(o.id),
        "lease_id": str(o.lease_id),
        "option_type": o.option_type,
        "exercise_window_start": o.exercise_window_start.isoformat() if o.exercise_window_start else None,
        "exercise_window_end": o.exercise_window_end.isoformat() if o.exercise_window_end else None,
        "notice_required_days": o.notice_required_days,
        "new_term_months": o.new_term_months,
        "new_rent_amount": float(o.new_rent_amount) if o.new_rent_amount is not None else None,
        "status": o.status,
        "notes": o.notes,
        "created_by_id": str(o.created_by_id) if o.created_by_id else None,
        "created_at": o.created_at.isoformat(),
        "updated_at": o.updated_at.isoformat(),
    }


@router.post("/{lease_id}/options", status_code=status.HTTP_201_CREATED)
async def create_option(
    lease_id: uuid.UUID,
    payload: OptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)

    from datetime import date as _date
    option = LeaseOption(
        lease_id=lease_id,
        option_type=payload.option_type,
        exercise_window_start=_date.fromisoformat(payload.exercise_window_start) if payload.exercise_window_start else None,
        exercise_window_end=_date.fromisoformat(payload.exercise_window_end) if payload.exercise_window_end else None,
        notice_required_days=payload.notice_required_days,
        new_term_months=payload.new_term_months,
        new_rent_amount=payload.new_rent_amount,
        notes=payload.notes,
        created_by_id=current_user.id,
    )
    db.add(option)
    await db.commit()
    await db.refresh(option)
    return _option_out(option)


@router.get("/{lease_id}/options")
async def list_options(
    lease_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseOption)
        .where(LeaseOption.lease_id == lease_id)
        .order_by(LeaseOption.exercise_window_end.asc().nulls_last())
    )
    return [_option_out(o) for o in result.scalars().all()]


@router.put("/{lease_id}/options/{option_id}")
async def update_option(
    lease_id: uuid.UUID,
    option_id: uuid.UUID,
    payload: OptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseOption).where(LeaseOption.id == option_id, LeaseOption.lease_id == lease_id)
    )
    option = result.scalar_one_or_none()
    if not option:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found")

    from datetime import date as _date
    if payload.option_type is not None:
        option.option_type = payload.option_type
    if payload.exercise_window_start is not None:
        option.exercise_window_start = _date.fromisoformat(payload.exercise_window_start)
    if payload.exercise_window_end is not None:
        option.exercise_window_end = _date.fromisoformat(payload.exercise_window_end)
    if payload.notice_required_days is not None:
        option.notice_required_days = payload.notice_required_days
    if payload.new_term_months is not None:
        option.new_term_months = payload.new_term_months
    if payload.new_rent_amount is not None:
        option.new_rent_amount = payload.new_rent_amount
    if payload.status is not None:
        option.status = payload.status
    if payload.notes is not None:
        option.notes = payload.notes
    option.updated_at = _utcnow()

    await db.commit()
    await db.refresh(option)
    return _option_out(option)


@router.delete("/{lease_id}/options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_option(
    lease_id: uuid.UUID,
    option_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    await _load_lease(db, lease_id, current_user.organization_id)
    result = await db.execute(
        select(LeaseOption).where(LeaseOption.id == option_id, LeaseOption.lease_id == lease_id)
    )
    option = result.scalar_one_or_none()
    if not option:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found")
    await db.delete(option)
    await db.commit()

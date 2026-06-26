import math
import uuid
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.base import _utcnow
from app.models.maintenance_ticket import MaintenanceTicket, TicketNote
from app.models.office import Office
from app.models.user import User
from app.utils.notifications import create_notification
from app.schemas.common import PaginatedResponse
from app.schemas.maintenance_ticket import (
    BulkTicketUpdate,
    MaintenanceTicketCreate,
    MaintenanceTicketResponse,
    MaintenanceTicketUpdate,
    TicketNoteCreate,
    TicketNoteResponse,
)
from app.services.activity_service import log_activity, compute_changes
from app.services.webhook_service import dispatch_webhook
from app.utils.search_vectors import update_search_vector
from app.utils.sorting import apply_sorting
from app.tasks.ticket_email import (
    send_high_priority_ticket_emails,
    send_ticket_created_emails,
    send_ticket_status_email,
    send_ticket_closed_email,
    send_ticket_assigned_email,
    send_mention_emails,
)

router = APIRouter()

_LOAD_OPTIONS = [
    joinedload(MaintenanceTicket.category),
    joinedload(MaintenanceTicket.office).joinedload(Office.manager),
    joinedload(MaintenanceTicket.created_by),
    joinedload(MaintenanceTicket.assigned_to),
    joinedload(MaintenanceTicket.vendor),
    joinedload(MaintenanceTicket.notes),
]


@router.get("/export")
async def export_tickets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.is_deleted.is_(False), MaintenanceTicket.organization_id == current_user.organization_id).order_by(MaintenanceTicket.created_at.desc())
    )
    tickets = result.scalars().unique().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Subject", "Priority", "Status", "Category", "Office", "Created By", "Assigned To", "Created At"])
    for t in tickets:
        writer.writerow([
            t.subject, t.priority, t.status, t.category.name if t.category else "",
            t.office.location_name if t.office else "", t.created_by.display_name if t.created_by else "",
            t.assigned_to.name if t.assigned_to else "", t.created_at,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=maintenance_tickets.csv"},
    )


@router.get("", response_model=PaginatedResponse[MaintenanceTicketResponse])
async def list_tickets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    office_id: uuid.UUID | None = Query(default=None),
    assigned_to_id: uuid.UUID | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(MaintenanceTicket).where(
        MaintenanceTicket.is_deleted.is_(False),
        MaintenanceTicket.organization_id == current_user.organization_id,
    )

    if status_filter:
        stmt = stmt.where(MaintenanceTicket.status == status_filter)
    if priority:
        stmt = stmt.where(MaintenanceTicket.priority == priority)
    if category_id:
        stmt = stmt.where(MaintenanceTicket.category_id == category_id)
    if office_id:
        stmt = stmt.where(MaintenanceTicket.office_id == office_id)
    if assigned_to_id:
        stmt = stmt.where(MaintenanceTicket.assigned_to_id == assigned_to_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    _TICKET_SORT_COLS = {
        "subject": MaintenanceTicket.subject,
        "priority": MaintenanceTicket.priority,
        "status": MaintenanceTicket.status,
        "created_at": MaintenanceTicket.created_at,
    }
    stmt = apply_sorting(stmt, sort_by, sort_order, _TICKET_SORT_COLS, [MaintenanceTicket.created_at.desc()])
    stmt = stmt.options(*_LOAD_OPTIONS).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    tickets = result.scalars().unique().all()

    return PaginatedResponse(
        items=[MaintenanceTicketResponse.model_validate(t, from_attributes=True) for t in tickets],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.patch("/bulk", response_model=list[MaintenanceTicketResponse])
async def bulk_update_tickets(
    payload: BulkTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(MaintenanceTicket).where(MaintenanceTicket.id.in_(payload.ids), MaintenanceTicket.is_deleted.is_(False))
    )
    tickets = result.scalars().all()
    if not tickets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tickets found")

    for ticket in tickets:
        if payload.status is not None:
            old_status = ticket.status
            ticket.status = payload.status
            if payload.status == "closed" and old_status != "closed":
                ticket.closed_at = _utcnow()
            elif payload.status != "closed" and old_status == "closed":
                ticket.closed_at = None
        if payload.assigned_to_id is not None:
            ticket.assigned_to_id = payload.assigned_to_id

    await db.commit()

    for ticket in tickets:
        await log_activity(
            db, user=current_user, action="updated",
            entity_type="maintenance_ticket", entity_id=ticket.id,
            entity_label=ticket.subject, changes={"bulk_update": {"status": payload.status}},
        )

    result = await db.execute(
        select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.id.in_(payload.ids))
    )
    return [MaintenanceTicketResponse.model_validate(t, from_attributes=True) for t in result.scalars().unique().all()]


@router.get("/{ticket_id}", response_model=MaintenanceTicketResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(False), MaintenanceTicket.organization_id == current_user.organization_id)
    )
    ticket = result.unique().scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return MaintenanceTicketResponse.model_validate(ticket, from_attributes=True)


@router.post("", response_model=MaintenanceTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: MaintenanceTicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor", "ticketer")),
):
    import logging
    log = logging.getLogger(__name__)

    # ---- 1. Insert the ticket. Failures here are the real bug; surface them. ----
    try:
        ticket = MaintenanceTicket(
            **payload.model_dump(),
            created_by_id=current_user.id,
            organization_id=current_user.organization_id,
        )
        db.add(ticket)
        await db.commit()
    except Exception as exc:
        log.exception("Failed to insert ticket: %s", exc)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not create ticket: {exc.__class__.__name__}: {exc}",
        ) from exc

    # ---- 2. Reload with relationships hydrated. ----
    try:
        result = await db.execute(
            select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.id == ticket.id)
        )
        created = result.unique().scalar_one()
    except Exception as exc:
        log.exception("Failed to reload created ticket %s: %s", ticket.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ticket saved but reload failed: {exc.__class__.__name__}: {exc}",
        ) from exc

    # ---- 3. Activity log (best-effort). ----
    try:
        await log_activity(
            db,
            user=current_user,
            action="created",
            entity_type="maintenance_ticket",
            entity_id=created.id,
            entity_label=created.subject,
        )
    except Exception as exc:
        log.exception("Failed to write activity log for ticket %s: %s", created.id, exc)
        try:
            await db.rollback()
        except Exception:
            pass

    # ---- 3.5. Search vector update (best-effort). ----
    try:
        await update_search_vector(db, "maintenance_tickets", created.id)
    except Exception:
        pass

    # ---- 3.6. Webhook dispatch (best-effort). ----
    try:
        await dispatch_webhook(
            db,
            org_id=current_user.organization_id,
            event_type="ticket.created",
            payload={
                "id": str(created.id),
                "subject": created.subject,
                "priority": created.priority,
                "status": created.status,
            },
        )
    except Exception:
        pass

    # ---- 4. Email notifications (best-effort). ----
    # Notify the office manager and assigned vendor that a ticket was created.
    created_id = created.id
    try:
        await send_ticket_created_emails(db, created)
    except Exception as exc:
        log.exception("Ticket-created email send failed for ticket %s: %s", created_id, exc)
        try:
            await db.rollback()
        except Exception:
            pass

    # High-priority tickets additionally notify configured rule recipients.
    if created.priority == "high":
        # Capture the id eagerly so the log call below cannot trigger a lazy
        # attribute reload after the session is in a failed-transaction state.
        try:
            await send_high_priority_ticket_emails(db, created)
        except Exception as exc:
            # Log first against a string we already have, then attempt rollback.
            log.exception("High-priority email send failed for ticket %s: %s", created_id, exc)
            try:
                await db.rollback()
            except Exception:
                pass

    # ---- 5. Serialize. Validation errors here are bugs in the data shape. ----
    try:
        return MaintenanceTicketResponse.model_validate(created, from_attributes=True)
    except Exception as exc:
        log.exception("Failed to serialize ticket %s for response: %s", created.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ticket created but response serialization failed: {exc.__class__.__name__}: {exc}",
        ) from exc


@router.put("/{ticket_id}", response_model=MaintenanceTicketResponse)
async def update_ticket(
    ticket_id: uuid.UUID,
    payload: MaintenanceTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(MaintenanceTicket).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(False)))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    update_data = payload.model_dump(exclude_unset=True)
    old_values = {k: getattr(ticket, k) for k in update_data}
    old_status = ticket.status
    old_assigned_to_id = ticket.assigned_to_id
    for field, value in update_data.items():
        setattr(ticket, field, value)

    # Track closed_at for SLA resolution time measurement
    if "status" in update_data:
        if ticket.status == "closed" and old_status != "closed":
            ticket.closed_at = _utcnow()
        elif ticket.status != "closed" and old_status == "closed":
            ticket.closed_at = None

    await db.commit()
    changes = compute_changes(old_values, update_data)
    await log_activity(db, user=current_user, action="updated", entity_type="maintenance_ticket", entity_id=ticket.id, entity_label=ticket.subject, changes=changes)
    try:
        await update_search_vector(db, "maintenance_tickets", ticket.id)
    except Exception:
        pass

    result = await db.execute(
        select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(False))
    )
    updated = result.unique().scalar_one()

    new_status = updated.status
    new_assigned_to_id = updated.assigned_to_id

    # Best-effort email notifications
    if old_status != new_status:
        try:
            await send_ticket_status_email(db, updated, old_status, new_status, current_user.display_name)
        except Exception:
            pass
        if new_status == "closed":
            try:
                await send_ticket_closed_email(db, updated, current_user.display_name)
            except Exception:
                pass
        try:
            await dispatch_webhook(
                db,
                org_id=current_user.organization_id,
                event_type="ticket.status_changed",
                payload={
                    "id": str(updated.id),
                    "subject": updated.subject,
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )
        except Exception:
            pass

    if old_assigned_to_id != new_assigned_to_id and updated.assigned_to and updated.assigned_to.email:
        try:
            await send_ticket_assigned_email(db, updated, updated.assigned_to.email)
        except Exception:
            pass
        # Create in-app notification for the assigned user (if they have an account)
        try:
            assignee_result = await db.execute(
                select(User).where(User.email == updated.assigned_to.email, User.is_active.is_(True))
            )
            assignee_user = assignee_result.scalar_one_or_none()
            if assignee_user:
                await create_notification(
                    db,
                    user_id=assignee_user.id,
                    kind="ticket_assigned",
                    title=f"Ticket assigned to you: {updated.subject}",
                    body=f"Priority: {updated.priority.capitalize()}",
                    entity_type="ticket",
                    entity_id=updated.id,
                )
        except Exception:
            pass

    return MaintenanceTicketResponse.model_validate(updated, from_attributes=True)


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(MaintenanceTicket).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(False)))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    label = ticket.subject
    ticket.is_deleted = True
    ticket.deleted_at = _utcnow()
    await db.commit()
    await log_activity(db, user=current_user, action="deleted", entity_type="maintenance_ticket", entity_id=ticket_id, entity_label=label)


@router.patch("/{ticket_id}/restore", response_model=MaintenanceTicketResponse)
async def restore_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await db.execute(select(MaintenanceTicket).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(True)))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found or not deleted")
    ticket.is_deleted = False
    ticket.deleted_at = None
    await db.commit()
    await log_activity(db, user=current_user, action="updated", entity_type="maintenance_ticket", entity_id=ticket_id, entity_label=ticket.subject)
    result = await db.execute(
        select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(False))
    )
    return MaintenanceTicketResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


# ─── Ticket Notes ────────────────────────────────────────────────────────────


@router.post("/{ticket_id}/notes", response_model=TicketNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_ticket_note(
    ticket_id: uuid.UUID,
    payload: TicketNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(select(MaintenanceTicket).options(*_LOAD_OPTIONS).where(MaintenanceTicket.id == ticket_id, MaintenanceTicket.is_deleted.is_(False)))
    ticket = result.unique().scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    order_result = await db.execute(
        select(func.coalesce(func.max(TicketNote.note_order), 0)).where(TicketNote.ticket_id == ticket_id)
    )
    next_order = order_result.scalar_one() + 1

    note = TicketNote(
        ticket_id=ticket_id,
        note_text=payload.note_text,
        note_order=next_order,
        created_by_id=current_user.id,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    # Best-effort mention emails
    try:
        await send_mention_emails(db, note, ticket)
    except Exception:
        pass

    return TicketNoteResponse.model_validate(note, from_attributes=True)


@router.delete("/{ticket_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket_note(
    ticket_id: uuid.UUID,
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(TicketNote).where(TicketNote.id == note_id, TicketNote.ticket_id == ticket_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    await db.delete(note)
    await db.commit()

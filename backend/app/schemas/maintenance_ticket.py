import uuid
from datetime import datetime
from pydantic import BaseModel

from app.schemas.office import ManagerResponse, OfficeResponse
from app.schemas.user import UserResponse


# ─── Ticket Categories ────────────────────────────────────────────────────────

class TicketCategoryCreate(BaseModel):
    name: str


class TicketCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Ticket Notes ────────────────────────────────────────────────────────────

class TicketNoteCreate(BaseModel):
    note_text: str


class TicketNoteResponse(BaseModel):
    id: uuid.UUID
    note_text: str
    note_order: int
    created_at: datetime
    created_by_id: uuid.UUID | None = None
    created_by: UserResponse | None = None

    model_config = {"from_attributes": True}


# ─── Maintenance Tickets ──────────────────────────────────────────────────────

class MaintenanceTicketCreate(BaseModel):
    subject: str
    priority: str
    status: str = "open"
    category_id: uuid.UUID
    office_id: uuid.UUID
    location_hours: str | None = None
    description: str
    assigned_to_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    scheduled_date: datetime | None = None
    estimated_duration_minutes: int | None = None
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    technician_name: str | None = None


class MaintenanceTicketUpdate(BaseModel):
    subject: str | None = None
    priority: str | None = None
    status: str | None = None
    category_id: uuid.UUID | None = None
    office_id: uuid.UUID | None = None
    location_hours: str | None = None
    description: str | None = None
    assigned_to_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    scheduled_date: datetime | None = None
    estimated_duration_minutes: int | None = None
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    technician_name: str | None = None


class BulkTicketUpdate(BaseModel):
    ids: list[uuid.UUID]
    status: str | None = None
    assigned_to_id: uuid.UUID | None = None


class MaintenanceTicketResponse(BaseModel):
    id: uuid.UUID
    subject: str
    priority: str
    status: str
    category_id: uuid.UUID
    category: TicketCategoryResponse
    office_id: uuid.UUID
    office: OfficeResponse
    location_hours: str | None
    description: str
    created_by_id: uuid.UUID
    created_by: UserResponse
    assigned_to_id: uuid.UUID | None
    assigned_to: ManagerResponse | None
    vendor_id: uuid.UUID | None = None
    vendor_completion_notes: str | None = None
    vendor_completed_at: datetime | None = None
    scheduled_date: datetime | None = None
    estimated_duration_minutes: int | None = None
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    technician_name: str | None = None
    notes: list[TicketNoteResponse] = []
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}

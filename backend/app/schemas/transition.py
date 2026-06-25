import uuid
from datetime import datetime
from pydantic import BaseModel


class ChecklistItemCreate(BaseModel):
    item_label: str
    response: str | None = None
    additional_notes: str | None = None
    extra_notes: str | None = None


class ChecklistItemUpdate(BaseModel):
    item_label: str | None = None
    response: str | None = None
    additional_notes: str | None = None
    extra_notes: str | None = None
    is_complete: bool | None = None


class ChecklistItemResponse(BaseModel):
    id: uuid.UUID
    item_label: str
    response: str | None
    additional_notes: str | None
    extra_notes: str | None
    sort_order: int
    is_complete: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TransitionCreate(BaseModel):
    office_id: uuid.UUID | None = None
    office_number: int | None = None
    transition_type: str
    address: str | None = None
    new_address: str | None = None
    status: str = "in_progress"
    notes: str | None = None


class TransitionUpdate(BaseModel):
    office_id: uuid.UUID | None = None
    office_number: int | None = None
    transition_type: str | None = None
    address: str | None = None
    new_address: str | None = None
    status: str | None = None
    notes: str | None = None


class TransitionResponse(BaseModel):
    id: uuid.UUID
    office_id: uuid.UUID | None
    office_number: int | None
    transition_type: str
    address: str | None
    new_address: str | None
    status: str
    sheet_name: str | None
    notes: str | None
    checklist_items: list[ChecklistItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

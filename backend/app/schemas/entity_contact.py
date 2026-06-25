import uuid
from datetime import datetime
from pydantic import BaseModel


class EntityContactCreate(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    contact_name: str
    title: str | None = None
    contact_type: str | None = None
    department: str | None = None
    is_primary: bool = False
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    notes: str | None = None


class EntityContactUpdate(BaseModel):
    contact_name: str | None = None
    title: str | None = None
    contact_type: str | None = None
    department: str | None = None
    is_primary: bool | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    notes: str | None = None


class EntityContactResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    contact_name: str
    title: str | None = None
    contact_type: str | None = None
    department: str | None = None
    is_primary: bool
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

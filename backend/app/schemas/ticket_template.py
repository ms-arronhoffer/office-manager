import uuid
from datetime import datetime
from pydantic import BaseModel

from app.schemas.maintenance_ticket import TicketCategoryResponse
from app.schemas.office import OfficeResponse, ManagerResponse


class TicketTemplateCreate(BaseModel):
    name: str
    subject: str
    description: str | None = None
    priority: str = "low"
    category_id: uuid.UUID | None = None
    office_id: uuid.UUID | None = None
    assigned_to_id: uuid.UUID | None = None


class TicketTemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    description: str | None = None
    priority: str | None = None
    category_id: uuid.UUID | None = None
    office_id: uuid.UUID | None = None
    assigned_to_id: uuid.UUID | None = None


class TicketTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    subject: str
    description: str | None
    priority: str
    category_id: uuid.UUID | None
    category: TicketCategoryResponse | None
    office_id: uuid.UUID | None
    office: OfficeResponse | None
    assigned_to_id: uuid.UUID | None
    assigned_to: ManagerResponse | None
    created_at: datetime

    model_config = {"from_attributes": True}

import uuid
from datetime import datetime
from pydantic import BaseModel

from app.schemas.maintenance_ticket import TicketCategoryResponse
from app.schemas.office import OfficeResponse, ManagerResponse
from app.schemas.user import UserResponse


class RecurringTicketRuleCreate(BaseModel):
    name: str
    subject: str
    description: str | None = None
    priority: str = "low"
    category_id: uuid.UUID | None = None
    office_id: uuid.UUID | None = None
    assigned_to_id: uuid.UUID | None = None
    frequency: str  # "daily" | "weekly" | "monthly"
    day_of_week: int | None = None
    day_of_month: int | None = None


class RecurringTicketRuleUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    description: str | None = None
    priority: str | None = None
    category_id: uuid.UUID | None = None
    office_id: uuid.UUID | None = None
    assigned_to_id: uuid.UUID | None = None
    frequency: str | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    is_active: bool | None = None


class RecurringTicketRuleResponse(BaseModel):
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
    created_by_id: uuid.UUID | None
    created_by: UserResponse | None
    frequency: str
    day_of_week: int | None
    day_of_month: int | None
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

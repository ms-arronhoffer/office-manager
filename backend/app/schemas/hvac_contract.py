import uuid
from datetime import date, datetime
from pydantic import BaseModel
from app.schemas.office import ManagerResponse


class HvacOfficeDetailResponse(BaseModel):
    id: uuid.UUID
    sheet_name: str | None
    hvac_contractor: str | None
    contractor_phone: str | None
    contractor_email: str | None
    contractor_address: str | None
    frequency: str | None
    responsibility_summary: str | None
    responsibility_detail: str | None
    lease_expiration: date | None
    lease_expiration_text: str | None
    notes: str | None

    model_config = {"from_attributes": True}


class HvacContractCreate(BaseModel):
    office_id: uuid.UUID | None = None
    office_number: int | None = None
    office_name: str | None = None
    hvac_company: str | None = None
    contact: str | None = None
    comments: str | None = None
    frequency: str | None = None
    last_serviced: str | None = None
    last_serviced_date: date | None = None
    next_service: str | None = None
    next_service_date: date | None = None
    manager_id: uuid.UUID | None = None
    landlord_handles: bool = False


class HvacContractUpdate(HvacContractCreate):
    pass


class HvacContractResponse(BaseModel):
    id: uuid.UUID
    office_id: uuid.UUID | None
    office_number: int | None
    office_name: str | None
    hvac_company: str | None
    contact: str | None
    comments: str | None
    frequency: str | None
    last_serviced: str | None
    last_serviced_date: date | None
    next_service: str | None
    next_service_date: date | None
    manager: ManagerResponse | None
    landlord_handles: bool
    details: list[HvacOfficeDetailResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

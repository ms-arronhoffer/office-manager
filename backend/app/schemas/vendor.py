import uuid
from datetime import datetime
from pydantic import BaseModel


class VendorOfficeRef(BaseModel):
    id: uuid.UUID
    location_name: str

    model_config = {"from_attributes": True}


class VendorCreate(BaseModel):
    company_name: str
    services: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    # Legacy free-form address (kept for back-compat / CSV imports).
    address: str | None = None
    # Structured address (preferred for new records).
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_preferred: bool = False
    notes: str | None = None
    office_ids: list[uuid.UUID] = []


class VendorUpdate(BaseModel):
    company_name: str | None = None
    services: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_preferred: bool | None = None
    notes: str | None = None
    office_ids: list[uuid.UUID] | None = None


class VendorResponse(BaseModel):
    id: uuid.UUID
    company_name: str
    services: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    address: str | None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_preferred: bool
    notes: str | None
    offices: list[VendorOfficeRef]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

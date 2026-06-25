import uuid
from datetime import datetime
from pydantic import BaseModel


class ManagementCompanyCreate(BaseModel):
    name: str
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    secondary_phone: str | None = None
    fax: str | None = None
    website: str | None = None
    portal_url: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    notes: str | None = None


class ManagementCompanyUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    secondary_phone: str | None = None
    fax: str | None = None
    website: str | None = None
    portal_url: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    notes: str | None = None


class ManagementCompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    secondary_phone: str | None = None
    fax: str | None = None
    website: str | None = None
    portal_url: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ManagementCompanyRef(BaseModel):
    """Lightweight reference embedded in other responses (e.g. landlords)."""

    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}

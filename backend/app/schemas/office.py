import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class ManagerResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None

    model_config = {"from_attributes": True}


class ManagerCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None


class ManagerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class OfficeCreate(BaseModel):
    office_number: int
    region_number: int | None = None
    location_type: str
    location_name: str
    manager_id: uuid.UUID | None = None
    is_active: bool = True
    mail_shipping: str | None = None
    notes: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone_number: str | None = None
    fax: str | None = None
    email: str | None = None
    other_names: str | None = None
    sector: str | None = None
    crown_property_on_site: str | None = None
    additional_info: str | None = None
    closing_notes: str | None = None
    total_sqft: Decimal | None = None
    usable_sqft: Decimal | None = None
    headcount_capacity: int | None = None
    current_headcount: int | None = None
    space_type: str | None = None
    # Property owner (may differ from landlord)
    owner_same_as_landlord: bool = False
    owner_name: str | None = None
    owner_company: str | None = None
    owner_email: str | None = None
    owner_phone: str | None = None
    owner_address_line_1: str | None = None
    owner_address_line_2: str | None = None
    owner_city: str | None = None
    owner_state: str | None = None
    owner_zip_code: str | None = None


class OfficeUpdate(BaseModel):
    office_number: int | None = None
    region_number: int | None = None
    location_type: str | None = None
    location_name: str | None = None
    manager_id: uuid.UUID | None = None
    is_active: bool | None = None
    mail_shipping: str | None = None
    notes: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone_number: str | None = None
    fax: str | None = None
    email: str | None = None
    other_names: str | None = None
    sector: str | None = None
    crown_property_on_site: str | None = None
    additional_info: str | None = None
    closing_notes: str | None = None
    total_sqft: Decimal | None = None
    usable_sqft: Decimal | None = None
    headcount_capacity: int | None = None
    current_headcount: int | None = None
    space_type: str | None = None
    # Property owner (may differ from landlord)
    owner_same_as_landlord: bool | None = None
    owner_name: str | None = None
    owner_company: str | None = None
    owner_email: str | None = None
    owner_phone: str | None = None
    owner_address_line_1: str | None = None
    owner_address_line_2: str | None = None
    owner_city: str | None = None
    owner_state: str | None = None
    owner_zip_code: str | None = None


class OfficeResponse(BaseModel):
    id: uuid.UUID
    office_number: int
    region_number: int | None
    location_type: str
    location_name: str
    manager: ManagerResponse | None
    is_active: bool
    mail_shipping: str | None
    notes: str | None
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    phone_number: str | None
    fax: str | None
    email: str | None
    other_names: str | None
    sector: str | None
    crown_property_on_site: str | None
    additional_info: str | None
    closing_notes: str | None
    total_sqft: Decimal | None
    usable_sqft: Decimal | None
    headcount_capacity: int | None
    current_headcount: int | None
    space_type: str | None
    # Property owner (may differ from landlord)
    owner_same_as_landlord: bool = False
    owner_name: str | None = None
    owner_company: str | None = None
    owner_email: str | None = None
    owner_phone: str | None = None
    owner_address_line_1: str | None = None
    owner_address_line_2: str | None = None
    owner_city: str | None = None
    owner_state: str | None = None
    owner_zip_code: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

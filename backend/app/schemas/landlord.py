import uuid
from datetime import datetime
from pydantic import BaseModel


class LandlordAdditionalNameResponse(BaseModel):
    id: uuid.UUID
    vendor_id: str | None
    co_name: str | None
    vendor_name: str | None
    other_names: str | None
    additional_names: str | None

    model_config = {"from_attributes": True}


class LandlordOfficeRef(BaseModel):
    id: uuid.UUID
    location_name: str

    model_config = {"from_attributes": True}


class LandlordContactCreate(BaseModel):
    contact_name: str
    title: str | None = None
    contact_type: str | None = None
    is_primary: bool = False
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class LandlordContactUpdate(BaseModel):
    contact_name: str | None = None
    title: str | None = None
    contact_type: str | None = None
    is_primary: bool | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class LandlordContactResponse(BaseModel):
    id: uuid.UUID
    landlord_id: uuid.UUID
    contact_name: str
    title: str | None
    contact_type: str | None
    is_primary: bool
    email: str | None
    phone: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LandlordCreate(BaseModel):
    ern: str | None = None
    office_name: str | None = None
    office_id: uuid.UUID | None = None
    # Offices owned by this landlord (one or many).
    office_ids: list[uuid.UUID] = []
    # Legacy free-form addresses (kept for back-compat).
    address: str | None = None
    contact_mailing_address: str | None = None
    # Structured property address.
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    # Structured mailing address.
    mailing_address_line_1: str | None = None
    mailing_address_line_2: str | None = None
    mailing_city: str | None = None
    mailing_state: str | None = None
    mailing_zip_code: str | None = None
    landlord_company: str | None = None
    contact_name: str | None = None
    title: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    secondary_phone: str | None = None
    fax: str | None = None
    website: str | None = None
    online_sign_in: str | None = None
    entity_type: str | None = None
    tax_id: str | None = None
    management_company: str | None = None
    preferred_payment_method: str | None = None
    payment_terms: str | None = None
    vendor_id: str | None = None
    notes: str | None = None


class LandlordUpdate(LandlordCreate):
    # On update, omitting office_ids leaves the associations unchanged.
    office_ids: list[uuid.UUID] | None = None


class LandlordResponse(BaseModel):
    id: uuid.UUID
    ern: str | None
    office_name: str | None
    office_id: uuid.UUID | None
    address: str | None
    contact_mailing_address: str | None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    mailing_address_line_1: str | None = None
    mailing_address_line_2: str | None = None
    mailing_city: str | None = None
    mailing_state: str | None = None
    mailing_zip_code: str | None = None
    landlord_company: str | None
    contact_name: str | None
    title: str | None
    contact_email: str | None
    contact_phone: str | None
    secondary_phone: str | None = None
    fax: str | None = None
    website: str | None = None
    online_sign_in: str | None
    entity_type: str | None = None
    tax_id: str | None = None
    management_company: str | None = None
    preferred_payment_method: str | None = None
    payment_terms: str | None = None
    vendor_id: str | None
    notes: str | None
    additional_names: list[LandlordAdditionalNameResponse]
    contacts: list[LandlordContactResponse]
    owned_offices: list[LandlordOfficeRef] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

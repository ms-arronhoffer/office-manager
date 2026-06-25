import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class HeatPumpServiceLogCreate(BaseModel):
    service_date: date | None = None
    invoice_number: str | None = None
    cost: Decimal | None = None
    description: str


class HeatPumpServiceLogResponse(BaseModel):
    id: uuid.UUID
    service_date: date | None
    invoice_number: str | None
    cost: Decimal | None
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HeatPumpResponse(BaseModel):
    id: uuid.UUID
    unit_id: str
    location_desc: str | None
    make: str | None
    model: str | None
    serial_number: str | None
    install_year: int | None
    notes: str | None
    service_logs: list[HeatPumpServiceLogResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class HeatPumpCreate(BaseModel):
    unit_id: str
    location_desc: str | None = None
    make: str | None = None
    model: str | None = None
    serial_number: str | None = None
    install_year: int | None = None
    notes: str | None = None


class HeatPumpUpdate(BaseModel):
    location_desc: str | None = None
    make: str | None = None
    model: str | None = None
    serial_number: str | None = None
    install_year: int | None = None
    notes: str | None = None


class HvacIssueCreate(BaseModel):
    issue_date: date | None = None
    description: str
    invoice_number: str | None = None
    cost: Decimal | None = None
    status: str = "open"


class HvacIssueUpdate(BaseModel):
    issue_date: date | None = None
    description: str | None = None
    invoice_number: str | None = None
    cost: Decimal | None = None
    status: str | None = None


class HvacIssueResponse(BaseModel):
    id: uuid.UUID
    issue_date: date | None
    description: str
    invoice_number: str | None
    cost: Decimal | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PmTaskCreate(BaseModel):
    equipment_category: str
    equipment_id: str | None = None
    task_description: str
    frequency: str | None = None
    can_in_house: bool = False
    last_pm_date: date | None = None
    next_due_date: date | None = None
    status: str = "Not Started"
    notes: str | None = None


class PmTaskUpdate(BaseModel):
    equipment_category: str | None = None
    equipment_id: str | None = None
    task_description: str | None = None
    frequency: str | None = None
    can_in_house: bool | None = None
    last_pm_date: date | None = None
    next_due_date: date | None = None
    status: str | None = None
    notes: str | None = None


class PmTaskResponse(BaseModel):
    id: uuid.UUID
    equipment_category: str
    equipment_id: str | None
    task_description: str
    frequency: str | None
    can_in_house: bool
    last_pm_date: date | None
    next_due_date: date | None
    status: str
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PmLogCreate(BaseModel):
    tech_name: str | None = None
    date_of_visit: date | None = None
    location: str | None = None
    equipment_type: str | None = None
    equipment_id: str | None = None
    task: str | None = None
    status: str | None = None
    notes: str | None = None


class PmLogUpdate(BaseModel):
    tech_name: str | None = None
    date_of_visit: date | None = None
    location: str | None = None
    equipment_type: str | None = None
    equipment_id: str | None = None
    task: str | None = None
    status: str | None = None
    notes: str | None = None


class PmLogResponse(BaseModel):
    id: uuid.UUID
    timestamp: datetime | None
    tech_name: str | None
    date_of_visit: date | None
    location: str | None
    equipment_type: str | None
    equipment_id: str | None
    task: str | None
    status: str | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BackflowResponse(BaseModel):
    id: uuid.UUID
    location_desc: str
    replaced_year: str | None
    last_tested_by: str | None
    last_tested_year: str | None
    reported_to: str | None
    notes: str | None

    model_config = {"from_attributes": True}


class BackflowCreate(BaseModel):
    location_desc: str
    replaced_year: str | None = None
    last_tested_by: str | None = None
    last_tested_year: str | None = None
    reported_to: str | None = None
    notes: str | None = None


class BackflowUpdate(BaseModel):
    location_desc: str | None = None
    replaced_year: str | None = None
    last_tested_by: str | None = None
    last_tested_year: str | None = None
    reported_to: str | None = None
    notes: str | None = None


class MaintenanceContractResponse(BaseModel):
    id: uuid.UUID
    contractor_name: str | None
    contract_start_date: date | None
    cancellation_notice: str | None
    equipment_covered: str | None
    notes: str | None

    model_config = {"from_attributes": True}


class MaintenanceContractCreate(BaseModel):
    contractor_name: str | None = None
    contract_start_date: date | None = None
    cancellation_notice: str | None = None
    equipment_covered: str | None = None
    notes: str | None = None


class MaintenanceContractUpdate(BaseModel):
    contractor_name: str | None = None
    contract_start_date: date | None = None
    cancellation_notice: str | None = None
    equipment_covered: str | None = None
    notes: str | None = None

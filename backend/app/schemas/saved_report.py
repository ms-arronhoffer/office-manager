import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Saved reports ──────────────────────────────────────────────────────────────

class SavedReportCreate(BaseModel):
    name: str
    dataset: str
    columns: list[str] | None = None
    filters: dict | None = None
    format: str = "pdf"


class SavedReportUpdate(BaseModel):
    name: str | None = None
    dataset: str | None = None
    columns: list[str] | None = None
    filters: dict | None = None
    format: str | None = None


class SavedReportResponse(BaseModel):
    id: uuid.UUID
    name: str
    dataset: str
    columns: list[str] | None
    filters: dict | None
    format: str
    created_by_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Report schedules ───────────────────────────────────────────────────────────

class ReportScheduleCreate(BaseModel):
    frequency: str  # daily | weekly | monthly
    day_of_week: int | None = None
    day_of_month: int | None = None
    recipients: list[str] = Field(default_factory=list)
    is_active: bool = True


class ReportScheduleUpdate(BaseModel):
    frequency: str | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    recipients: list[str] | None = None
    is_active: bool | None = None


class ReportScheduleResponse(BaseModel):
    id: uuid.UUID
    saved_report_id: uuid.UUID
    frequency: str
    day_of_week: int | None
    day_of_month: int | None
    recipients: list[str]
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── AI natural-language report builder ─────────────────────────────────────────

class ReportBuildRequest(BaseModel):
    prompt: str


class ReportBuildResponse(BaseModel):
    """A *draft* saved-report definition for the user to confirm before saving."""
    dataset: str
    columns: list[str] | None
    filters: dict
    title: str
    model: str

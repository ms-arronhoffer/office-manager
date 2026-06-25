import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WizardConfigCreate(BaseModel):
    name: str
    description: str | None = None
    steps: list[dict[str, Any]]
    is_active: bool = True
    is_default: bool = False


class WizardConfigUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class WizardConfigResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    steps: list[dict[str, Any]]
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

import uuid
from datetime import datetime
from pydantic import BaseModel


class ActivityLogResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_display_name: str
    action: str
    entity_type: str
    entity_id: uuid.UUID
    entity_label: str
    changes: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

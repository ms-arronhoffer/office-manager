import uuid
from datetime import datetime
from pydantic import BaseModel


class AttachmentResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    original_filename: str
    content_type: str
    file_size: int
    uploaded_by: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

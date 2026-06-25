"""Pydantic schemas for the Lease Abstract clause grid."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class AbstractFieldSchema(BaseModel):
    """A single field definition from the clause catalog."""

    key: str
    label: str
    type: str
    options: list[str] | None = None


class AbstractClause(BaseModel):
    """A clause category merged with any stored content for one lease."""

    category_key: str
    name: str
    group: str
    order: int
    fields: list[AbstractFieldSchema]
    status: str
    content: dict | None = None
    notes: str | None = None
    updated_at: datetime | None = None


class AbstractClauseUpdate(BaseModel):
    """Upsert payload for a single clause."""

    content: dict | None = None
    notes: str | None = None
    # Optional explicit status override; when omitted the status is auto-derived.
    status: str | None = None


class AbstractSummary(BaseModel):
    total: int
    contains_content: int
    needs_content: int
    incomplete: int


class LeaseAbstractResponse(BaseModel):
    lease_id: uuid.UUID
    clauses: list[AbstractClause]
    summary: AbstractSummary

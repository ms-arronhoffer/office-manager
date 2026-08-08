"""Import batches: replay protection and a durable record of every load.

Bulk loads are the single easiest way to corrupt a ledger. Re-uploading last
month's spreadsheet "just to be safe" must not silently double-post rent, and a
migration that reports success must be provable afterwards.

Each upload is fingerprinted by a SHA-256 of its bytes plus the target entity.
An identical fingerprint for the same organization is recognised as a replay and
is refused rather than re-applied, unless the caller explicitly forces it. The
batch also retains per-row exceptions so "5 skipped" can be turned back into the
five specific rows and reasons that were skipped.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

IMPORT_BATCH_STATUSES = ("completed", "completed_with_errors", "failed", "rejected_replay")


def content_fingerprint(entity: str, payload: bytes) -> str:
    """Stable identity for an upload, used to detect an accidental replay."""
    digest = hashlib.sha256()
    digest.update(entity.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(payload)
    return digest.hexdigest()


class ImportBatch(TimestampMixin, Base):
    """One bulk load attempt, with its outcome and row-level exceptions."""

    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # "xlsx", "buildium", "cam_history", ...
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # SHA-256 of entity + file bytes; the replay-protection key.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Per-row exceptions, so a skipped row can be explained and corrected.
    row_errors: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

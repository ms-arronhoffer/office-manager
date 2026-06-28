"""Saved & scheduled reports (Item 4).

``SavedReport`` captures a reusable report definition over the existing
dataset/template engine (:data:`app.services.report_service.DATASET_CONFIGS`):
the dataset, the chosen columns, a filter map and an export format. It deliberately
stores *only* the building blocks the report engine already understands — never
free-form SQL.

``ReportSchedule`` attaches a delivery cadence to a saved report so a scheduler
job can render and email it on a recurring basis, reusing the same
``frequency``/``next_run_at`` vocabulary as the recurring-ticket engine.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Export formats supported by ReportService.generate.
REPORT_FORMATS = ("csv", "xlsx", "pdf")


class SavedReport(TimestampMixin, Base):
    __tablename__ = "saved_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset: Mapped[str] = mapped_column(String(50), nullable=False)
    # Subset of the dataset's available columns; empty/None means "all columns".
    columns: Mapped[list[str] | None] = mapped_column(PG_ARRAY(String(100)), nullable=True)
    # Filter map validated against the dataset's filters_config.
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    schedules: Mapped[list["ReportSchedule"]] = relationship(
        back_populates="saved_report",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ReportSchedule(TimestampMixin, Base):
    __tablename__ = "report_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    saved_report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)  # daily|weekly|monthly
    day_of_week: Mapped[int | None] = mapped_column(nullable=True)   # 0=Mon..6=Sun
    day_of_month: Mapped[int | None] = mapped_column(nullable=True)  # 1-31
    recipients: Mapped[list[str]] = mapped_column(PG_ARRAY(String(255)), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    saved_report: Mapped["SavedReport"] = relationship(back_populates="schedules")

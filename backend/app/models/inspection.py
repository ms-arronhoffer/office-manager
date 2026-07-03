"""Property inspection models (Phase 1.5).

Reusable inspection checklists and the inspection instances performed against an
office. Fits the facilities / HVAC positioning: a manager builds a template of
checklist items once, then runs inspections that snapshot those items into
per-instance results (pass / fail / n/a) with notes. Photos attach through the
existing generic attachments system with ``entity_type="inspection"``.

  - ``InspectionTemplate``     — a reusable checklist (name + items).
  - ``InspectionTemplateItem`` — one checklist line on a template.
  - ``Inspection``            — an inspection performed on an office.
  - ``InspectionItemResult``   — the recorded result for one checklist line,
                                 snapshotted from the template at creation time.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Inspection instance lifecycle states.
INSPECTION_STATUSES = {"scheduled", "in_progress", "completed", "canceled"}
# Per-item and overall outcomes.
INSPECTION_RESULTS = {"pass", "fail", "na"}


class InspectionTemplate(TimestampMixin, Base):
    """A reusable inspection checklist."""

    __tablename__ = "inspection_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    items: Mapped[list["InspectionTemplateItem"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="InspectionTemplateItem.sort_order",
    )


class InspectionTemplateItem(TimestampMixin, Base):
    """A single checklist line belonging to an inspection template."""

    __tablename__ = "inspection_template_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    template: Mapped["InspectionTemplate"] = relationship(back_populates="items")


class Inspection(TimestampMixin, Base):
    """An inspection performed against an office."""

    __tablename__ = "inspections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inspection_templates.id", ondelete="SET NULL"), nullable=True
    )
    office_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="scheduled", nullable=False)
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inspector_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Overall pass/fail/na, computed on completion from required items.
    overall_result: Mapped[str | None] = mapped_column(String(4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list["InspectionItemResult"]] = relationship(
        back_populates="inspection",
        cascade="all, delete-orphan",
        order_by="InspectionItemResult.sort_order",
    )


class InspectionItemResult(TimestampMixin, Base):
    """The recorded outcome for one checklist line on an inspection."""

    __tablename__ = "inspection_item_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The template item this was snapshotted from (nullable: item may be edited
    # or the template deleted after the inspection is created).
    template_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inspection_template_items.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # One of INSPECTION_RESULTS, or NULL while the inspection is in progress.
    result: Mapped[str | None] = mapped_column(String(4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    inspection: Mapped["Inspection"] = relationship(back_populates="results")

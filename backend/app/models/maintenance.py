"""Maintenance models — the property-maintenance program.

Replaces the narrow "HVAC" surface with a broader **Maintenance** domain that
covers the recurring upkeep a property manager is responsible for. Three tables
model the program:

* :class:`MaintenanceAsset` — a physical thing that is serviced (a rooftop HVAC
  unit, a sprinkler riser, an elevator cab, a trash compactor, …).
* :class:`MaintenanceTask` — a (usually recurring) maintenance obligation. A task
  may be tied to an asset or stand alone, carries a due date, an optionally
  assigned vendor, and reminder settings.
* :class:`MaintenanceLog` — a completion record (a service visit) against a task
  and/or asset.

Everything is scoped to an ``organization_id`` so the feature is multi-tenant,
unlike the legacy single-tenant ``hq_*`` HVAC tables.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    String, Integer, Boolean, Date, DateTime, Text, ForeignKey, Index, Numeric,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


# ---------------------------------------------------------------------------
# Category catalog
# ---------------------------------------------------------------------------
# The six maintenance domains a property manager covers, each with the common
# sub-topics. Surfaced to the frontend via the router so the UI dropdowns and
# the backend validation share a single source of truth.

MAINTENANCE_CATEGORIES: dict[str, dict] = {
    "hvac": {
        "label": "HVAC Systems",
        "subtopics": {
            "filter_change": "Filter Changes",
            "coil_cleaning": "Coil Cleaning",
            "boiler_chiller_inspection": "Boiler & Chiller Inspections",
            "duct_cleaning": "Duct Cleaning",
            "refrigerant_leak_check": "Refrigerant Leak Check",
            "thermostat_calibration": "Thermostat / BMS Calibration",
        },
    },
    "fire_life_safety": {
        "label": "Fire & Life Safety",
        "subtopics": {
            "sprinkler_inspection": "Sprinkler Systems",
            "fire_alarm_testing": "Fire Alarms & Panels",
            "extinguisher_check": "Extinguishers",
            "emergency_exit_lighting": "Emergency & Exit Lighting",
            "fire_pump_standpipe": "Fire Pump & Standpipes",
            "kitchen_hood_suppression": "Kitchen Hood Suppression",
        },
    },
    "plumbing_backflow": {
        "label": "Plumbing & Backflow",
        "subtopics": {
            "backflow_testing": "Backflow Prevention Devices",
            "drain_jetting": "Drain Jetting",
            "sump_pump": "Sump Pumps & Ejectors",
            "water_heater_flush": "Water Heater / Boiler Flush",
            "grease_trap": "Grease Trap Pumping",
        },
    },
    "refuse_waste": {
        "label": "Refuse & Waste Management",
        "subtopics": {
            "trash_chute": "Trash Chutes & Rooms",
            "compactor_baler": "Compactors & Balers",
            "bulk_waste": "Bulk Waste Coordination",
            "pest_control": "Pest Control",
        },
    },
    "exterior_structural": {
        "label": "Exterior & Structural",
        "subtopics": {
            "roofing": "Roofing",
            "parking_sidewalks": "Parking Lots & Sidewalks",
            "landscaping": "Landscaping",
            "facade_masonry": "Façade / Masonry",
            "gutters_drains": "Gutters & Downspouts",
        },
    },
    "elevators_lifts": {
        "label": "Elevators & Lifts",
        "subtopics": {
            "cab_mechanical_inspection": "Cab & Mechanical Inspections",
            "state_certification": "State Certifications",
            "emergency_phone_test": "Emergency Phone / Comm Test",
        },
    },
}

MAINTENANCE_CATEGORY_KEYS: tuple[str, ...] = tuple(MAINTENANCE_CATEGORIES.keys())

# Recurrence cadences a task may use.
MAINTENANCE_FREQUENCIES: tuple[str, ...] = (
    "monthly",
    "quarterly",
    "semi_annual",
    "annual",
    "seasonal",
    "as_needed",
)

# Lifecycle statuses for a task.
MAINTENANCE_TASK_STATUSES: tuple[str, ...] = (
    "scheduled",
    "in_progress",
    "completed",
    "overdue",
    "on_hold",
)

MAINTENANCE_ASSET_STATUSES: tuple[str, ...] = (
    "active",
    "needs_repair",
    "needs_replacement",
    "retired",
)


def is_valid_subtopic(category: str, subtopic: str | None) -> bool:
    """Return whether ``subtopic`` belongs to ``category`` (None is allowed)."""
    if subtopic is None:
        return True
    cat = MAINTENANCE_CATEGORIES.get(category)
    if not cat:
        return False
    return subtopic in cat["subtopics"]


class MaintenanceAsset(TimestampMixin, Base):
    __tablename__ = "maintenance_assets"
    __table_args__ = (
        Index("idx_maint_asset_org", "organization_id"),
        Index("idx_maint_asset_category", "category"),
        Index("idx_maint_asset_office", "office_id"),
        Index("idx_maint_asset_vendor", "vendor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    subtopic: Mapped[str | None] = mapped_column(String(60), nullable=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    is_regulatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    certification_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor: Mapped["Vendor | None"] = relationship(foreign_keys=[vendor_id])
    office: Mapped["Office | None"] = relationship(foreign_keys=[office_id])
    tasks: Mapped[list["MaintenanceTask"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    logs: Mapped[list["MaintenanceLog"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class MaintenanceTask(TimestampMixin, Base):
    __tablename__ = "maintenance_tasks"
    __table_args__ = (
        Index("idx_maint_task_org", "organization_id"),
        Index("idx_maint_task_category", "category"),
        Index("idx_maint_task_office", "office_id"),
        Index("idx_maint_task_vendor", "vendor_id"),
        Index("idx_maint_task_due", "next_due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("maintenance_assets.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    subtopic: Mapped[str | None] = mapped_column(String(60), nullable=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="scheduled", nullable=False)
    is_regulatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Reminder configuration: fire an email this many days before next_due_date.
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_days_before: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    reminder_recipients: Mapped[list[str]] = mapped_column(
        PG_ARRAY(String(255)), nullable=False, default=list
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset: Mapped["MaintenanceAsset | None"] = relationship(
        back_populates="tasks", foreign_keys=[asset_id]
    )
    vendor: Mapped["Vendor | None"] = relationship(foreign_keys=[vendor_id])
    office: Mapped["Office | None"] = relationship(foreign_keys=[office_id])
    logs: Mapped[list["MaintenanceLog"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class MaintenanceLog(Base):
    __tablename__ = "maintenance_logs"
    __table_args__ = (
        Index("idx_maint_log_org", "organization_id"),
        Index("idx_maint_log_task", "task_id"),
        Index("idx_maint_log_asset", "asset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("maintenance_tasks.id", ondelete="CASCADE"), nullable=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("maintenance_assets.id", ondelete="CASCADE"), nullable=True
    )
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    performed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    task: Mapped["MaintenanceTask | None"] = relationship(
        back_populates="logs", foreign_keys=[task_id]
    )
    asset: Mapped["MaintenanceAsset | None"] = relationship(
        back_populates="logs", foreign_keys=[asset_id]
    )
    vendor: Mapped["Vendor | None"] = relationship(foreign_keys=[vendor_id])


from app.models.vendor import Vendor  # noqa: E402
from app.models.office import Office  # noqa: E402

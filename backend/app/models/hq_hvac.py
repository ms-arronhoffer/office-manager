import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, Date, Text, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class HqHeatPump(TimestampMixin, Base):
    __tablename__ = "hq_heat_pumps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    unit_id: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    location_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    install_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refrigerant_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tonnage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    seer_rating: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    filter_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    warranty_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    service_logs: Mapped[list["HqHeatPumpServiceLog"]] = relationship(
        back_populates="heat_pump", cascade="all, delete-orphan"
    )


class HqHeatPumpServiceLog(Base):
    __tablename__ = "hq_heat_pump_service_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    heat_pump_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hq_heat_pumps.id", ondelete="CASCADE"), nullable=False
    )
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    heat_pump: Mapped["HqHeatPump"] = relationship(back_populates="service_logs")


class HqHvacIssue(TimestampMixin, Base):
    __tablename__ = "hq_hvac_issues"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)


class HqPmTask(TimestampMixin, Base):
    __tablename__ = "hq_pm_tasks"
    __table_args__ = (
        Index("idx_pm_tasks_category", "equipment_category"),
        Index("idx_pm_tasks_due", "next_due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    equipment_category: Mapped[str] = mapped_column(String(30), nullable=False)
    equipment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    can_in_house: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_pm_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Not Started", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HqPmLog(Base):
    __tablename__ = "hq_pm_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime | None] = mapped_column(nullable=True)
    tech_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_visit: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    equipment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)


class HqMaintenanceContract(TimestampMixin, Base):
    __tablename__ = "hq_maintenance_contracts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contractor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_notice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment_covered: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    visits: Mapped[list["HqMaintenanceVisit"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )


class HqMaintenanceVisit(Base):
    __tablename__ = "hq_maintenance_visits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hq_maintenance_contracts.id", ondelete="CASCADE"), nullable=True
    )
    visit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    tech_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    contract: Mapped["HqMaintenanceContract | None"] = relationship(back_populates="visits")


class HqTowerSprayLog(Base):
    __tablename__ = "hq_tower_spray_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)


class HqBackflow(TimestampMixin, Base):
    __tablename__ = "hq_backflows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    location_desc: Mapped[str] = mapped_column(Text, nullable=False)
    replaced_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_tested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_tested_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reported_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

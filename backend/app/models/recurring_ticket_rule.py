import uuid
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, Boolean, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class RecurringTicketRule(TimestampMixin, Base):
    __tablename__ = "recurring_ticket_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ticket_categories.id"), nullable=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)  # "daily" | "weekly" | "monthly"
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0=Mon..6=Sun
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-31
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped["TicketCategory | None"] = relationship(foreign_keys=[category_id])
    office: Mapped["Office | None"] = relationship(foreign_keys=[office_id])
    assigned_to: Mapped["Manager | None"] = relationship(foreign_keys=[assigned_to_id])
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])


from app.models.maintenance_ticket import TicketCategory  # noqa: E402
from app.models.office import Office, Manager  # noqa: E402
from app.models.user import User  # noqa: E402

import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class TicketTemplate(TimestampMixin, Base):
    __tablename__ = "ticket_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ticket_categories.id"), nullable=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("managers.id"), nullable=True)

    category: Mapped["TicketCategory | None"] = relationship(foreign_keys=[category_id])
    office: Mapped["Office | None"] = relationship(foreign_keys=[office_id])
    assigned_to: Mapped["Manager | None"] = relationship(foreign_keys=[assigned_to_id])


from app.models.maintenance_ticket import TicketCategory  # noqa: E402
from app.models.office import Office, Manager  # noqa: E402

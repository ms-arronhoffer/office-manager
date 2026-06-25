import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class OfficeTransition(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "office_transitions"
    __table_args__ = (
        Index("idx_transitions_type", "transition_type"),
        Index("idx_transitions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    office_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transition_type: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expiration: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    office: Mapped["Office | None"] = relationship(back_populates="transitions")
    checklist_items: Mapped[list["TransitionChecklistItem"]] = relationship(
        back_populates="transition", cascade="all, delete-orphan"
    )


class TransitionChecklistItem(TimestampMixin, Base):
    __tablename__ = "transition_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("office_transitions.id", ondelete="CASCADE"), nullable=False
    )
    item_label: Mapped[str] = mapped_column(String(500), nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    transition: Mapped["OfficeTransition"] = relationship(back_populates="checklist_items")


from app.models.office import Office  # noqa: E402

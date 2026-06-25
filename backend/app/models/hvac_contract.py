import uuid
from datetime import date, datetime
from sqlalchemy import Integer, Boolean, Date, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class HvacContract(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "hvac_contracts"
    __table_args__ = (
        Index("idx_hvac_contracts_next", "next_service_date"),
        Index("idx_hvac_contracts_office_id", "office_id"),
        Index("idx_hvac_contracts_manager_id", "manager_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    office_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    office_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    hvac_company: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_serviced: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_serviced_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_service: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    landlord_handles: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    office: Mapped["Office | None"] = relationship(back_populates="hvac_contracts")
    manager: Mapped["Manager | None"] = relationship("Manager")
    details: Mapped[list["HvacOfficeDetail"]] = relationship(
        back_populates="hvac_contract", cascade="all, delete-orphan"
    )


class HvacOfficeDetail(TimestampMixin, Base):
    __tablename__ = "hvac_office_details"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hvac_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hvac_contracts.id", ondelete="CASCADE"), nullable=True
    )
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    hvac_contractor: Mapped[str | None] = mapped_column(Text, nullable=True)
    contractor_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    contractor_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    contractor_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibility_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibility_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    lease_expiration_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    hvac_contract: Mapped["HvacContract | None"] = relationship(back_populates="details")


from app.models.office import Office, Manager  # noqa: E402

import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Text, ForeignKey, Index, Table, Column, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


vendor_offices = Table(
    "vendor_offices",
    Base.metadata,
    Column("vendor_id", ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column("office_id", ForeignKey("offices.id", ondelete="CASCADE"), primary_key=True),
)


class Vendor(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        Index("idx_vendors_company_name", "company_name"),
        Index("idx_vendors_is_preferred", "is_preferred"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    services: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Legacy free-form address kept for back-compat with existing data and CSV imports.
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured address (preferred for new records).
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    portal_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    portal_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    offices: Mapped[list["Office"]] = relationship(
        secondary=vendor_offices, back_populates="vendors"
    )
    tickets: Mapped[list["MaintenanceTicket"]] = relationship(
        back_populates="vendor", lazy="select"
    )


from app.models.office import Office  # noqa: E402

import uuid
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class Manager(TimestampMixin, Base):
    __tablename__ = "managers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)

    offices: Mapped[list["Office"]] = relationship(back_populates="manager")


class Office(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "offices"
    __table_args__ = (
        Index("idx_offices_number", "office_number"),
        Index("idx_offices_manager", "manager_id"),
        Index("idx_offices_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    office_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_type: Mapped[str] = mapped_column(String(20), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mail_shipping: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    fax: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    other_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    crown_property_on_site: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    closing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Space & Occupancy (Phase 2.2)
    total_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    usable_sqft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    headcount_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    space_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    manager: Mapped["Manager | None"] = relationship(back_populates="offices")
    leases: Mapped[list["Lease"]] = relationship(back_populates="office")
    landlords: Mapped[list["Landlord"]] = relationship(back_populates="office")
    owner_landlords: Mapped[list["Landlord"]] = relationship(
        secondary="landlord_offices", back_populates="owned_offices"
    )
    transitions: Mapped[list["OfficeTransition"]] = relationship(back_populates="office")
    hvac_contracts: Mapped[list["HvacContract"]] = relationship(back_populates="office")
    vendors: Mapped[list["Vendor"]] = relationship(
        secondary="vendor_offices", back_populates="offices"
    )


# Avoid circular imports - these are resolved at runtime by SQLAlchemy
from app.models.lease import Lease  # noqa: E402
from app.models.landlord import Landlord  # noqa: E402
from app.models.transition import OfficeTransition  # noqa: E402
from app.models.hvac_contract import HvacContract  # noqa: E402
from app.models.vendor import Vendor  # noqa: E402

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, Boolean, ForeignKey, Index, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.management_company import ManagementCompany


# Association table for the many-to-many relationship between a landlord and the
# offices they own. A landlord may own one or many offices, and an office may be
# owned by one or many landlords.
landlord_offices = Table(
    "landlord_offices",
    Base.metadata,
    Column("landlord_id", ForeignKey("landlords.id", ondelete="CASCADE"), primary_key=True),
    Column("office_id", ForeignKey("offices.id", ondelete="CASCADE"), primary_key=True),
)


class Landlord(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "landlords"
    __table_args__ = (
        Index("idx_landlords_office_id", "office_id"),
        Index("idx_landlords_ern", "ern"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    ern: Mapped[str | None] = mapped_column(String(20), nullable=True)
    office_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    # Legacy free-form addresses kept for back-compat with existing data.
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_mailing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured property address (preferred).
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Structured mailing address (separate from property address).
    mailing_address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailing_address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailing_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mailing_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    mailing_zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    landlord_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Additional contact channels.
    secondary_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    fax: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    online_sign_in: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Business / legal entity details.
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Legacy free-form management company name (kept for back-compat). New
    # records should link to a ManagementCompany via management_company_id.
    management_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    management_company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("management_companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Billing / payment details.
    preferred_payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    office: Mapped["Office | None"] = relationship(back_populates="landlords")
    management_company_ref: Mapped["ManagementCompany | None"] = relationship(
        "ManagementCompany", back_populates="landlords"
    )
    # Offices owned by this landlord (one or many).
    owned_offices: Mapped[list["Office"]] = relationship(
        secondary=landlord_offices, back_populates="owner_landlords"
    )
    additional_names: Mapped[list["LandlordAdditionalName"]] = relationship(
        back_populates="landlord", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["LandlordContact"]] = relationship(
        back_populates="landlord", cascade="all, delete-orphan"
    )


class LandlordAdditionalName(Base):
    __tablename__ = "landlord_additional_names"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    landlord_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("landlords.id", ondelete="CASCADE"), nullable=True
    )
    vendor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    co_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    other_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    landlord: Mapped["Landlord | None"] = relationship(back_populates="additional_names")


class LandlordContact(TimestampMixin, Base):
    __tablename__ = "landlord_contacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    landlord_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("landlords.id", ondelete="CASCADE"), nullable=False
    )
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    landlord: Mapped["Landlord"] = relationship(back_populates="contacts")


from app.models.office import Office  # noqa: E402

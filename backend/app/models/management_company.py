import uuid

from sqlalchemy import String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class ManagementCompany(SoftDeleteMixin, TimestampMixin, Base):
    """A property management company that may manage one or many landlords'
    properties. Modeled as a first-class entity so the same company can be
    referenced by multiple landlords without duplicating its details."""

    __tablename__ = "management_companies"
    __table_args__ = (
        Index("idx_management_companies_name", "name"),
        Index("idx_management_companies_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Primary point of contact.
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    secondary_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Web presence / portal the team uses to interact with this company.
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portal_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Structured address.
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Landlords whose properties this company manages.
    landlords: Mapped[list["Landlord"]] = relationship(back_populates="management_company_ref")


from app.models.landlord import Landlord  # noqa: E402

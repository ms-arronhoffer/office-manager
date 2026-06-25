import uuid

from sqlalchemy import String, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


# Entity types that may own additional contacts. Kept as a plain string column
# (rather than an enum) so new entity types can adopt contacts without a schema
# migration.
ENTITY_CONTACT_TYPES = ("landlord", "vendor", "management_company")


class EntityContact(TimestampMixin, Base):
    """A reusable, polymorphic "additional contact" that can be attached to any
    entity (landlord, vendor, management company, ...). Each row carries a few
    fields to identify the person and route communication to them."""

    __tablename__ = "entity_contacts"
    __table_args__ = (
        Index("idx_entity_contacts_entity", "entity_type", "entity_id"),
        Index("idx_entity_contacts_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # Polymorphic owner.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Identity / routing fields.
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Role/category that helps direct who to contact (e.g. billing, maintenance).
    contact_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

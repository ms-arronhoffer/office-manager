"""Tenant / resident domain model (Phase 2.1 — org-as-lessor).

The existing :class:`~app.models.lease.Lease` models the organisation as the
*lessee* — the org rents office/commercial space *from* an external landlord.
Property management flips that relationship: here the organisation is the
*lessor*, leasing residential/commercial units it owns or manages *to* outside
occupants. The two lease directions are deliberately distinct tables so they can
coexist without overloading either model.

Entities
--------
* :class:`RentalUnit`    — a leasable unit/space within an :class:`Office`
  (property) that the org offers to tenants. Carries market rent and a derived
  occupancy status.
* :class:`Resident`      — a first-class occupant/tenant record (a person or
  business that occupies a unit), independent of any single lease so a resident
  can be tracked across multiple tenancies.
* :class:`ResidentLease` — the org-as-lessor lease of one unit for a term, with
  rent/deposit terms and a lifecycle status.
* :class:`ResidentLeaseOccupant` — the lease-to-resident link (many-to-many),
  capturing each occupant's role on the lease (primary, co-signer, occupant,
  guarantor).

Amounts are USD-only for now, matching the rest of the accounting modules; a
``currency`` column is carried for forward compatibility.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

# Occupancy status of a leasable unit. ``occupied`` is normally derived from an
# active resident lease but is stored so units can be marked unavailable
# (e.g. down for renovation) independently of any lease.
UNIT_STATUSES = ("available", "occupied", "unavailable")

# Lifecycle of an org-as-lessor lease.
RESIDENT_LEASE_STATUSES = ("draft", "pending", "active", "ended", "terminated")

# Lifecycle of a resident record.
RESIDENT_STATUSES = ("prospect", "current", "past")

# Role an occupant plays on a lease.
OCCUPANT_ROLES = ("primary", "co_signer", "occupant", "guarantor")

# Term structure of an org-as-lessor lease. Mirrors the richness of the
# org-as-lessee :class:`~app.models.lease.Lease` classification fields.
LEASE_TYPES = ("fixed_term", "month_to_month", "at_will", "short_term")

# Statuses that count a lease as currently occupying its unit.
ACTIVE_LEASE_STATUSES = ("pending", "active")


class RentalUnit(SoftDeleteMixin, TimestampMixin, Base):
    """A leasable unit/space the organisation offers to tenants (org-as-lessor)."""

    __tablename__ = "rental_units"
    __table_args__ = (
        UniqueConstraint("office_id", "unit_number", name="uq_rental_unit_office_number"),
        Index("idx_rental_units_office", "office_id"),
        Index("idx_rental_units_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # The property (office) this unit belongs to.
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id"), nullable=True, index=True
    )
    unit_number: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    square_feet: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    market_rent: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="available", nullable=False, server_default="available"
    )
    # Address & marketing detail — mirrors the richer Office (Portfolio) fields so
    # a unit can be described as fully as a portfolio property.
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amenities: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    office: Mapped["Office | None"] = relationship("Office")
    leases: Mapped[list["ResidentLease"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )


class Resident(SoftDeleteMixin, TimestampMixin, Base):
    """A first-class occupant/tenant record, independent of any single lease."""

    __tablename__ = "residents"
    __table_args__ = (
        Index("idx_residents_status", "status"),
        Index("idx_residents_last_name", "last_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Mailing / contact address, mirroring the Portfolio landlord/owner detail.
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="prospect", nullable=False, server_default="prospect"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional link to the accounts-receivable counterparty used to bill this
    # resident for rent (Phase 2.3). Created lazily on first billing.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    lease_links: Mapped[list["ResidentLeaseOccupant"]] = relationship(
        back_populates="resident", cascade="all, delete-orphan"
    )


class ResidentLease(SoftDeleteMixin, TimestampMixin, Base):
    """An org-as-lessor lease of a single unit to one or more residents."""

    __tablename__ = "resident_leases"
    __table_args__ = (
        Index("idx_resident_leases_unit", "unit_id"),
        Index("idx_resident_leases_status", "status"),
        Index("idx_resident_leases_end_date", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rental_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional human-facing label; falls back to the unit reference in the UI.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False, server_default="draft"
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    move_in_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    move_out_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rent_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Billing cadence label (e.g. "monthly", "weekly", "annual").
    rent_frequency: Mapped[str] = mapped_column(
        String(20), default="monthly", nullable=False, server_default="monthly"
    )
    rent_due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_deposit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Richer lease terms mirroring the Portfolio lease classification/financials.
    lease_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rent_escalation_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    late_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    late_fee_grace_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pet_deposit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    renewal_option: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The lease template this lease was prepared from. Remembering it lets staff
    # send the lease for e-signature without re-selecting a template, and drives
    # which custom merge fields (``template_field_values``) the lease captures.
    lease_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lease_templates.id", ondelete="SET NULL"), nullable=True
    )
    # Values for any custom ``{{merge_field}}`` placeholders a template defines
    # beyond the standard lease/unit/occupant fields, keyed by field name.
    template_field_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    unit: Mapped["RentalUnit"] = relationship(back_populates="leases")
    occupants: Mapped[list["ResidentLeaseOccupant"]] = relationship(
        back_populates="lease",
        cascade="all, delete-orphan",
        order_by="ResidentLeaseOccupant.created_at",
    )


class ResidentLeaseOccupant(TimestampMixin, Base):
    """Link between a :class:`ResidentLease` and a :class:`Resident` (occupant)."""

    __tablename__ = "resident_lease_occupants"
    __table_args__ = (
        UniqueConstraint(
            "lease_id", "resident_id", name="uq_resident_lease_occupant"
        ),
        Index("idx_resident_lease_occupants_lease", "lease_id"),
        Index("idx_resident_lease_occupants_resident", "resident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resident_leases.id", ondelete="CASCADE"), nullable=False
    )
    resident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20), default="primary", nullable=False, server_default="primary"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    lease: Mapped["ResidentLease"] = relationship(back_populates="occupants")
    resident: Mapped["Resident"] = relationship(back_populates="lease_links")


# Avoid circular imports - resolved at runtime by SQLAlchemy.
from app.models.office import Office  # noqa: E402

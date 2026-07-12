"""Self-storage domain model (org-as-operator).

Self storage is modelled as a third *primary category* alongside commercial and
residential. It deliberately **reuses** two existing entities so the domain
shares maintenance, inspections, space, portal, screening, and AR/GL wiring:

* the facility (*location*) is an existing :class:`~app.models.office.Office`
  (referenced by ``office_id``), and
* the tenant/occupant is an existing :class:`~app.models.resident.Resident`
  (linked through :class:`StorageAgreementOccupant`).

New, storage-specific entities:

* :class:`StorageUnit`            — a rentable unit/space at a facility, with its
  physical size, unit type, climate-control flag, feature flags, and rate tiers.
* :class:`StorageAgreement`       — the (typically month-to-month) rental
  agreement of one unit to one or more residents, with rate, deposit, billing
  cadence, tenant-protection/insurance plan, and gate access.
* :class:`StorageAgreementOccupant` — the agreement-to-resident link.
* :class:`StorageReservation`     — a prospect hold on a unit or size tier.
* :class:`StorageRatePlan`        — street/standard rates per size tier and an
  optional scheduled rent increase.
* :class:`StorageLienEvent`       — an entry in the delinquency → lien → auction
  lifecycle audit trail.

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

# Occupancy/operational status of a storage unit.
STORAGE_UNIT_STATUSES = (
    "available",
    "reserved",
    "occupied",
    "maintenance",
    "overlocked",
    "lien",
    "auction",
)

# Physical unit type.
STORAGE_UNIT_TYPES = (
    "drive_up",
    "interior",
    "outdoor",
    "locker",
    "vehicle",
    "parking",
)

# Lock / overlock state (independent of occupancy).
STORAGE_LOCK_STATES = ("unlocked", "tenant_locked", "overlocked")

# Lifecycle of a storage rental agreement (full delinquency workflow).
STORAGE_AGREEMENT_STATUSES = (
    "draft",
    "active",
    "pending_move_out",
    "ended",
    "delinquent",
    "in_lien",
    "auctioned",
)

# Statuses that count an agreement as currently occupying its unit.
STORAGE_ACTIVE_STATUSES = ("active", "pending_move_out", "delinquent", "in_lien")

# Role an occupant plays on an agreement.
STORAGE_OCCUPANT_ROLES = ("primary", "co_signer", "authorized", "alternate")

# Reservation lifecycle.
STORAGE_RESERVATION_STATUSES = (
    "held",
    "converted",
    "cancelled",
    "expired",
)

# Steps of the delinquency → lien → auction lifecycle.
STORAGE_LIEN_STEPS = (
    "late",
    "overlock",
    "lien_notice",
    "auction_scheduled",
    "auctioned",
    "redeemed",
    "released",
)


class StorageUnit(SoftDeleteMixin, TimestampMixin, Base):
    """A rentable self-storage unit/space at a facility (Office)."""

    __tablename__ = "storage_units"
    __table_args__ = (
        UniqueConstraint("office_id", "unit_number", name="uq_storage_unit_office_number"),
        Index("idx_storage_units_office", "office_id"),
        Index("idx_storage_units_status", "status"),
        Index("idx_storage_units_size_tier", "size_tier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # The facility (Office) this unit belongs to.
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id"), nullable=True, index=True
    )
    unit_number: Mapped[str] = mapped_column(String(50), nullable=False)
    building: Mapped[str | None] = mapped_column(String(50), nullable=True)
    row: Mapped[str | None] = mapped_column(String(50), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Size: width x length in feet, with a derived square-footage and optional
    # cubic feet (for climate / valuation), plus a human size label ("10x10").
    width_ft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    height_ft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    square_feet: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cubic_feet: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    size_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Rate-grouping tier (e.g. "small", "medium", "large", "10x10").
    size_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)

    unit_type: Mapped[str] = mapped_column(
        String(20), default="interior", nullable=False, server_default="interior"
    )
    # Temperature/humidity-controlled ("conditioned") space.
    climate_controlled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # Feature flags.
    has_power: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    is_alarmed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    drive_up_access: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    ground_floor: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    elevator_access: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    access_24hr: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # Rate amounts: the published street rate, a standard/board rate, the current
    # in-place rate for the occupying tenant, and any promotional rate.
    street_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    standard_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    in_place_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    promo_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default="available", nullable=False, server_default="available"
    )
    lock_state: Mapped[str] = mapped_column(
        String(20), default="unlocked", nullable=False, server_default="unlocked"
    )
    # Gate access zone/area for gated facilities.
    gate_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    office: Mapped["Office | None"] = relationship("Office")
    agreements: Mapped[list["StorageAgreement"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )


class StorageAgreement(SoftDeleteMixin, TimestampMixin, Base):
    """An org-as-operator rental agreement of one unit to one or more residents."""

    __tablename__ = "storage_agreements"
    __table_args__ = (
        Index("idx_storage_agreements_unit", "unit_id"),
        Index("idx_storage_agreements_status", "status"),
        Index("idx_storage_agreements_move_out", "move_out_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False, server_default="draft"
    )
    # Terms.
    rent_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    security_deposit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    admin_fee: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    billing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_cycle: Mapped[str] = mapped_column(
        String(20), default="monthly", nullable=False, server_default="monthly"
    )
    autopay_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    autopay_method: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Tenant protection / insurance plan.
    insurance_plan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insurance_coverage: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    insurance_premium: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # Gate access.
    gate_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Late-fee terms (mirrors ResidentLease richness).
    late_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    late_fee_grace_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    move_in_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    move_out_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    unit: Mapped["StorageUnit"] = relationship(back_populates="agreements")
    occupants: Mapped[list["StorageAgreementOccupant"]] = relationship(
        back_populates="agreement",
        cascade="all, delete-orphan",
        order_by="StorageAgreementOccupant.created_at",
    )
    lien_events: Mapped[list["StorageLienEvent"]] = relationship(
        back_populates="agreement",
        cascade="all, delete-orphan",
        order_by="StorageLienEvent.event_date",
    )


class StorageAgreementOccupant(TimestampMixin, Base):
    """Link between a :class:`StorageAgreement` and a :class:`Resident`."""

    __tablename__ = "storage_agreement_occupants"
    __table_args__ = (
        UniqueConstraint(
            "agreement_id", "resident_id", name="uq_storage_agreement_occupant"
        ),
        Index("idx_storage_agreement_occupants_agreement", "agreement_id"),
        Index("idx_storage_agreement_occupants_resident", "resident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_agreements.id", ondelete="CASCADE"), nullable=False
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

    agreement: Mapped["StorageAgreement"] = relationship(back_populates="occupants")
    resident: Mapped["Resident"] = relationship()


class StorageReservation(SoftDeleteMixin, TimestampMixin, Base):
    """A prospect hold on a specific unit or a size tier."""

    __tablename__ = "storage_reservations"
    __table_args__ = (
        Index("idx_storage_reservations_status", "status"),
        Index("idx_storage_reservations_unit", "unit_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id"), nullable=True, index=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storage_units.id", ondelete="SET NULL"), nullable=True
    )
    resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="SET NULL"), nullable=True
    )
    # Prospect contact when not yet a resident record.
    prospect_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prospect_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prospect_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quoted_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="held", nullable=False, server_default="held"
    )
    hold_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class StorageRatePlan(SoftDeleteMixin, TimestampMixin, Base):
    """Street/standard rates for a size tier plus an optional scheduled increase."""

    __tablename__ = "storage_rate_plans"
    __table_args__ = (
        Index("idx_storage_rate_plans_office", "office_id"),
        Index("idx_storage_rate_plans_size_tier", "size_tier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # Optional facility scope; null means an org-wide rate for the tier.
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id"), nullable=True
    )
    size_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    street_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    standard_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    # Scheduled rent increase (revenue management): as of ``increase_effective_date``,
    # raise in-place rates by either a flat amount or a percentage.
    increase_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    increase_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    increase_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class StorageLienEvent(TimestampMixin, Base):
    """An entry in the delinquency → lien → auction lifecycle audit trail."""

    __tablename__ = "storage_lien_events"
    __table_args__ = (
        Index("idx_storage_lien_events_agreement", "agreement_id"),
        Index("idx_storage_lien_events_step", "step"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    agreement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_agreements.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Free-form metadata (e.g. auction house, sale proceeds).
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    agreement: Mapped["StorageAgreement"] = relationship(back_populates="lien_events")


class StorageCharge(SoftDeleteMixin, TimestampMixin, Base):
    """A recurring billing schedule for a storage agreement (rent/insurance/etc.).

    Mirrors :class:`~app.models.rent.RentCharge` but keyed to a storage
    agreement. Billing posts through the shared AR/GL via
    ``self_storage_service``.
    """

    __tablename__ = "storage_charges"
    __table_args__ = (
        Index("idx_storage_charges_agreement", "storage_agreement_id"),
        Index("idx_storage_charges_active", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    storage_agreement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage_agreements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charge_type: Mapped[str] = mapped_column(
        String(20), default="rent", nullable=False, server_default="rent"
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(
        String(20), default="monthly", nullable=False, server_default="monthly"
    )
    day_of_month: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1"
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    grace_days: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False, server_default="5"
    )
    late_fee_type: Mapped[str] = mapped_column(
        String(20), default="none", nullable=False, server_default="none"
    )
    late_fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    revenue_account_code: Mapped[str] = mapped_column(
        String(20), default="4100", nullable=False, server_default="4100"
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    last_billed_period: Mapped[date | None] = mapped_column(Date, nullable=True)


# Recognised storage charge types.
STORAGE_CHARGE_TYPES = ("rent", "insurance", "admin", "late_fee", "other")


# Avoid circular imports - resolved at runtime by SQLAlchemy.
from app.models.office import Office  # noqa: E402,F401
from app.models.resident import Resident  # noqa: E402,F401

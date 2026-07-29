import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, Date, Text, ForeignKey, Index, Numeric, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class Lease(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "leases"
    __table_args__ = (
        Index("idx_leases_expiration", "lease_expiration"),
        Index("idx_leases_year", "expiration_year"),
        Index("idx_leases_notice_date", "lease_notice_date"),
        Index("idx_leases_office_id", "office_id"),
        Index("idx_leases_manager_id", "manager_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    office_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offices.id"), nullable=True)
    lease_name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    lease_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    lessor_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_period: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_given_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiration_year: Mapped[int] = mapped_column(Integer, nullable=False)

    # ASC 842 / IFRS 16 financial fields
    lease_commencement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accounting_standard: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lease_classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    payment_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    annual_escalation_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    incremental_borrowing_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    initial_direct_costs: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    lease_incentives: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    prepaid_rent: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    residual_value_guarantee: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    is_short_term_lease: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_low_value_lease: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True, server_default="USD")

    office: Mapped["Office | None"] = relationship(back_populates="leases")
    manager: Mapped["Manager | None"] = relationship("Manager")
    notes: Mapped[list["LeaseNote"]] = relationship(back_populates="lease", cascade="all, delete-orphan")
    operating_expenses: Mapped[list["OperatingExpense"]] = relationship(
        back_populates="lease", cascade="all, delete-orphan", lazy="select"
    )
    cam_entries: Mapped[list["LeaseCamEntry"]] = relationship(
        back_populates="lease",
        cascade="all, delete-orphan",
        order_by="LeaseCamEntry.year",
        lazy="select",
    )


class LeaseNote(Base):
    __tablename__ = "lease_notes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id", ondelete="CASCADE"), nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    note_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)

    lease: Mapped["Lease"] = relationship(back_populates="notes")


# Charge structure for a CAM (common-area-maintenance) schedule row.
#   fixed            — ``amount`` is the CAM charge for that year.
#   percent_increase — ``percent_increase`` is the % increase applied over the
#                      prior year's CAM charge (e.g. 0.030000 = 3%).
CAM_CHARGE_TYPES = {"fixed", "percent_increase"}


class LeaseCamEntry(TimestampMixin, Base):
    """A single year's CAM (common-area-maintenance) charge for a lease.

    CAM often varies year to year across the life of a lease and may be quoted
    either as a fixed dollar amount or as a percentage increase over the prior
    year. This table lets each lease-year be configured independently. An
    optional ``gl_account_id`` attributes the CAM expense to a chart-of-accounts
    entry so it flows into GL reporting.
    """

    __tablename__ = "lease_cam_entries"
    __table_args__ = (
        Index("idx_lease_cam_entries_lease", "lease_id"),
        Index("idx_lease_cam_entries_gl", "gl_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    lease_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leases.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # One of CAM_CHARGE_TYPES; defaults to a fixed amount.
    charge_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="fixed", server_default="fixed"
    )
    # Fixed CAM amount for the year (used when charge_type == "fixed").
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Percentage increase over the prior year (used when
    # charge_type == "percent_increase"); e.g. 0.030000 = 3%.
    percent_increase: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    # Optional GL account this CAM expense is attributed to.
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    lease: Mapped["Lease"] = relationship(back_populates="cam_entries")
    gl_account: Mapped["GLAccount | None"] = relationship("GLAccount")


from app.models.office import Office, Manager  # noqa: E402
from app.models.general_ledger import GLAccount  # noqa: E402

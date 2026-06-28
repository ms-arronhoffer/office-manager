"""Insurance certificate model — tracks COIs for vendors and landlords."""
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import String, Text, ForeignKey, Index, Date, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


CERT_TYPES = ("general_liability", "workers_comp", "auto", "umbrella", "other")

# Number of days before expiration at which a certificate is "expiring soon".
EXPIRING_SOON_DAYS = 30


def certificate_status(expiration_date: date | None, today: date | None = None) -> str:
    """Compute a COI's compliance status from its expiration date.

    Shared by the admin certificates router and the vendor portal so both
    surfaces report identical ``active``/``expiring_soon``/``expired``/``unknown``
    states.
    """
    if expiration_date is None:
        return "unknown"
    if today is None:
        today = date.today()
    if expiration_date < today:
        return "expired"
    if (expiration_date - today).days <= EXPIRING_SOON_DAYS:
        return "expiring_soon"
    return "active"


class InsuranceCertificate(TimestampMixin, Base):
    __tablename__ = "insurance_certificates"
    __table_args__ = (
        Index("idx_inscert_vendor", "vendor_id"),
        Index("idx_inscert_landlord", "landlord_id"),
        Index("idx_inscert_expiration", "expiration_date"),
        Index("idx_inscert_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    # One of vendor_id or landlord_id must be set
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=True
    )
    landlord_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("landlords.id", ondelete="CASCADE"), nullable=True
    )
    certificate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    insurer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    limits: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vendor: Mapped["Vendor | None"] = relationship(foreign_keys=[vendor_id])
    landlord: Mapped["Landlord | None"] = relationship(foreign_keys=[landlord_id])


from app.models.vendor import Vendor  # noqa: E402
from app.models.landlord import Landlord  # noqa: E402

"""Owner / trust accounting domain model (Phase 2.6 — org-as-manager).

Property management companies collect rent and pay expenses *on behalf of* the
people or entities that actually own the buildings. That money is not the
manager's — it is held in trust and owed back to the owner, net of management
fees and reimbursable expenses. This module models that relationship:

Entities
--------
* :class:`PropertyOwner`   — an individual or company that owns one or more
  managed properties. Carries a default management-fee rate and 1099-friendly
  tax details.
* :class:`OwnerProperty`   — links an owner to an :class:`~app.models.office.Office`
  (property) with an ownership percentage and an optional per-property
  management-fee override, so co-ownership and mixed portfolios are supported.
* :class:`OwnerLedgerEntry`— a single line in the owner's running ledger. The
  ledger is the source of truth for what is owed to the owner: income increases
  the balance, while expenses, management fees, and distributions decrease it.
  Amounts are stored *signed* (positive = owed to owner, negative = reduces the
  balance) so a statement is a straight running sum.
* :class:`OwnerDistribution` — a payout (check/ACH/wire) that returns held funds
  to the owner. Posting a distribution writes the matching (negative) ledger
  entry and a GL journal entry (``Dr Due to Owners / Cr Cash``).
* :class:`TrustAccount`    — a segregated trust/escrow bank account that holds
  owner funds. These are compliance-sensitive (broker trust-accounting rules
  vary by jurisdiction), so every trust account carries a compliance-review
  workflow and is flagged for review until an admin signs off.

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin

# Whether the owner is a person or a business entity.
OWNER_TYPES = ("individual", "company")

# Lifecycle of an owner relationship.
OWNER_STATUSES = ("active", "inactive")

# Kinds of ledger movement. Income raises the owner balance; expenses,
# management fees, and distributions lower it; adjustments can go either way.
LEDGER_ENTRY_TYPES = ("income", "expense", "management_fee", "distribution", "adjustment")

# How a distribution/payout is remitted to the owner.
DISTRIBUTION_METHODS = ("check", "ach", "wire", "other")

# Lifecycle of a distribution/payout.
DISTRIBUTION_STATUSES = ("pending", "paid", "void")

# Lifecycle of a trust/escrow account.
TRUST_ACCOUNT_STATUSES = ("active", "closed")

# Compliance-review workflow for a trust/escrow account. Trust accounting is
# regulated, so accounts start ``pending`` and must be reviewed before they are
# considered clean; ``flagged`` blocks payouts from the account.
COMPLIANCE_STATUSES = ("pending", "under_review", "approved", "flagged")


class PropertyOwner(SoftDeleteMixin, TimestampMixin, Base):
    """An individual or company that owns one or more managed properties."""

    __tablename__ = "property_owners"
    __table_args__ = (
        Index("idx_property_owners_status", "status"),
        Index("idx_property_owners_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    owner_type: Mapped[str] = mapped_column(
        String(20), default="individual", nullable=False, server_default="individual"
    )
    # Display name (company name, or the individual's full name).
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Kept for 1099 reporting; never exposed through the owner portal.
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Default management-fee rate (percent of collected income) applied unless a
    # property-level override is set on the :class:`OwnerProperty` link.
    management_fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0"), nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, server_default="active"
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    properties: Mapped[list["OwnerProperty"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class OwnerProperty(TimestampMixin, Base):
    """Links a :class:`PropertyOwner` to a property (:class:`Office`)."""

    __tablename__ = "owner_properties"
    __table_args__ = (
        UniqueConstraint("owner_id", "office_id", name="uq_owner_property"),
        Index("idx_owner_properties_owner", "owner_id"),
        Index("idx_owner_properties_office", "office_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("property_owners.id", ondelete="CASCADE"), nullable=False
    )
    office_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offices.id", ondelete="CASCADE"), nullable=False
    )
    # Share of the property this owner holds (0-100). Multiple owners of a single
    # property should sum to 100, but that is not enforced at the DB level.
    ownership_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100"), nullable=False, server_default="100"
    )
    # Optional per-property override of the owner's default management-fee rate.
    management_fee_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    owner: Mapped["PropertyOwner"] = relationship(back_populates="properties")
    office: Mapped["Office"] = relationship("Office")


class OwnerLedgerEntry(TimestampMixin, Base):
    """A single signed line in an owner's running trust ledger."""

    __tablename__ = "owner_ledger_entries"
    __table_args__ = (
        Index("idx_owner_ledger_owner", "owner_id"),
        Index("idx_owner_ledger_date", "entry_date"),
        Index("idx_owner_ledger_type", "entry_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("property_owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional property the movement is attributed to.
    office_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offices.id", ondelete="SET NULL"), nullable=True
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Signed: positive increases the balance owed to the owner (income), negative
    # decreases it (expense, management fee, distribution).
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    # Provenance tags so generated entries can be traced/de-duplicated.
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional GL journal entry this ledger line mirrors.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )

    owner: Mapped["PropertyOwner"] = relationship("PropertyOwner")


class OwnerDistribution(TimestampMixin, Base):
    """A payout of held funds back to an owner (reduces the trust balance)."""

    __tablename__ = "owner_distributions"
    __table_args__ = (
        Index("idx_owner_distributions_owner", "owner_id"),
        Index("idx_owner_distributions_status", "status"),
        Index("idx_owner_distributions_date", "distribution_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("property_owners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distribution_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    method: Mapped[str] = mapped_column(
        String(20), default="ach", nullable=False, server_default="ach"
    )
    # Check number / ACH trace / wire reference.
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, server_default="pending"
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    # Trust/escrow account the funds are paid from (optional).
    trust_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trust_accounts.id", ondelete="SET NULL"), nullable=True
    )
    # The ledger line and GL entry created when the distribution posts.
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owner_ledger_entries.id", ondelete="SET NULL"), nullable=True
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )

    owner: Mapped["PropertyOwner"] = relationship("PropertyOwner")


class TrustAccount(SoftDeleteMixin, TimestampMixin, Base):
    """A segregated trust/escrow bank account holding owner funds.

    Trust accounting is regulated, so each account carries a compliance-review
    workflow. Accounts are ``compliance_review_required`` and start ``pending``;
    an admin must review them, and a ``flagged`` account blocks payouts.
    """

    __tablename__ = "trust_accounts"
    __table_args__ = (
        Index("idx_trust_accounts_status", "status"),
        Index("idx_trust_accounts_compliance", "compliance_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Only the last few digits are stored; never the full account number.
    account_number_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # The GL cash/asset account this trust account maps to (optional).
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, server_default="active"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Compliance-review workflow ──────────────────────────────────────────
    compliance_review_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    compliance_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, server_default="pending"
    )
    compliance_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    compliance_reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    compliance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# Resolved at runtime by SQLAlchemy to avoid circular imports.
from app.models.office import Office  # noqa: E402,F401

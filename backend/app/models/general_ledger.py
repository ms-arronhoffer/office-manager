"""Persisted general-ledger models for audit-grade GAAP output (Phase 2).

Provides a double-entry general ledger:
  - GLAccount       — chart-of-accounts entry (org-scoped)
  - AccountingPeriod — a fiscal month that can be open or closed
  - JournalEntry     — a balanced journal entry header
  - JournalEntryLine — an individual debit/credit line

Posting into a closed period is prevented at the service layer so that
reported financials for a closed period remain immutable.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Account types and their normal balance side.
ACCOUNT_TYPES = {"asset", "liability", "equity", "revenue", "expense"}
# Types whose normal balance is a debit (assets and expenses); the rest credit.
DEBIT_NORMAL_TYPES = {"asset", "expense"}


class GLAccount(TimestampMixin, Base):
    """A single chart-of-accounts entry, scoped to an organization."""

    __tablename__ = "gl_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_gl_accounts_org_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # One of ACCOUNT_TYPES
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="account"
    )

    @property
    def normal_balance(self) -> str:
        return "debit" if self.type in DEBIT_NORMAL_TYPES else "credit"


class AccountingPeriod(TimestampMixin, Base):
    """A fiscal month for an organization that may be open or closed."""

    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "year", "month", name="uq_accounting_periods_org_ym"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    # "open" or "closed"
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="period"
    )


class JournalEntry(TimestampMixin, Base):
    """A balanced double-entry journal entry header."""

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounting_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Origin of the entry, e.g. "manual", "lease", or "cam".
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    # Optional reference to the originating record (e.g. a lease id or CAM
    # reconciliation id) as text.
    source_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # "draft" or "posted"
    status: Mapped[str] = mapped_column(String(10), default="posted", nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    posted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    period: Mapped["AccountingPeriod"] = relationship(back_populates="entries")
    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="JournalEntryLine.line_number",
    )


class JournalEntryLine(TimestampMixin, Base):
    """A single debit/credit line within a journal entry."""

    __tablename__ = "journal_entry_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    debit: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    credit: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)

    entry: Mapped["JournalEntry"] = relationship(back_populates="lines")
    account: Mapped["GLAccount"] = relationship(back_populates="lines")

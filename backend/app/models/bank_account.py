"""Bank-reconciliation models (Phase 1.2).

A lightweight bank register and statement-reconciliation ledger that sits on top
of the audit-grade general ledger. Each bank account maps to a GL cash account so
the imported bank activity can be proved against the book (GL) balance:

  - ``BankAccount``        — a real-world bank account mapped to a GL cash account.
  - ``BankTransaction``    — a single imported (or manually entered) bank line;
                             a signed amount (positive deposit, negative
                             withdrawal), optionally cleared into a reconciliation.
  - ``BankReconciliation`` — a statement reconciliation for a bank account with a
                             beginning/ending balance and the set of transactions
                             cleared against it.

The reconciliation is the classic bank-rec proof: starting from the statement
``beginning_balance``, the sum of the *cleared* transactions must equal the
statement ``ending_balance`` before the reconciliation can be completed. Anything
not yet cleared is an outstanding (uncleared) item.

Amounts are USD-only; multi-currency / FX handling is deferred. A ``currency``
column is carried defaulting to ``USD`` so the schema is forward-compatible.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Bank-transaction clearing states.
TRANSACTION_STATUSES = {"unmatched", "cleared"}
# Reconciliation workflow states.
RECONCILIATION_STATUSES = {"in_progress", "completed"}
# Recognised import sources for a bank transaction.
IMPORT_SOURCES = {"csv", "ofx", "manual"}


class BankAccount(TimestampMixin, Base):
    """A bank account mapped to a general-ledger cash account, scoped to an org."""

    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The GL cash (asset) account this bank account reconciles against.
    gl_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=False, index=True
    )
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Last four digits of the account number (never store the full number).
    account_number_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    gl_account = relationship("GLAccount")
    transactions: Mapped[list["BankTransaction"]] = relationship(
        back_populates="bank_account",
        cascade="all, delete-orphan",
    )
    reconciliations: Mapped[list["BankReconciliation"]] = relationship(
        back_populates="bank_account",
        cascade="all, delete-orphan",
    )


class BankTransaction(TimestampMixin, Base):
    """A single imported bank line, optionally cleared into a reconciliation."""

    __tablename__ = "bank_transactions"
    __table_args__ = (
        # OFX/QFX transactions carry a unique FITID; use it to make re-imports
        # idempotent per account. Postgres treats NULLs as distinct, so manual
        # rows (no FITID) are never blocked by this constraint.
        UniqueConstraint("bank_account_id", "fitid", name="uq_bank_txn_account_fitid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Signed amount: positive = deposit/credit, negative = withdrawal/debit.
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # OFX/QFX FITID used for de-duplication on import.
    fitid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    import_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "unmatched" (outstanding) or "cleared" (reconciled).
    status: Mapped[str] = mapped_column(String(20), default="unmatched", nullable=False)
    # The reconciliation that cleared this transaction, when cleared.
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_reconciliations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optional link to the GL journal entry this bank line corresponds to.
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
    )

    bank_account: Mapped["BankAccount"] = relationship(back_populates="transactions")
    reconciliation: Mapped["BankReconciliation | None"] = relationship(
        back_populates="transactions"
    )


class BankReconciliation(TimestampMixin, Base):
    """A statement reconciliation proving cleared activity to an ending balance."""

    __tablename__ = "bank_reconciliations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    beginning_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    ending_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    # "in_progress" or "completed".
    status: Mapped[str] = mapped_column(
        String(15), default="in_progress", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    bank_account: Mapped["BankAccount"] = relationship(
        back_populates="reconciliations"
    )
    transactions: Mapped[list["BankTransaction"]] = relationship(
        back_populates="reconciliation",
        order_by="BankTransaction.txn_date",
    )


from app.models.general_ledger import GLAccount  # noqa: E402,F401

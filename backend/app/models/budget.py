"""Budgeting models (Phase 1.4).

GL-account-level annual budgets and their per-account allocation lines, used to
produce budget-vs-actual variance reporting layered on the existing general
ledger. A ``Budget`` is an annual plan for a fiscal year; each ``BudgetLine``
sets a planned amount for one GL account, expressed on the account's normal
balance side (e.g. a positive expense budget, a positive revenue budget).

Budgets never post to the GL — actuals are read live from journal entries at
report time, so the ledger stays the single source of truth.
"""

import uuid
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Budget lifecycle states.
BUDGET_STATUSES = {"draft", "active", "archived"}


class Budget(TimestampMixin, Base):
    """An annual, GL-account-level budget for a fiscal year."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "fiscal_year", "name", name="uq_budgets_org_year_name"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(15), default="draft", nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lines: Mapped[list["BudgetLine"]] = relationship(
        back_populates="budget",
        cascade="all, delete-orphan",
        order_by="BudgetLine.created_at",
    )


class BudgetLine(TimestampMixin, Base):
    """A planned annual amount for a single GL account within a budget."""

    __tablename__ = "budget_lines"
    __table_args__ = (
        UniqueConstraint("budget_id", "account_id", name="uq_budget_lines_budget_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=False, index=True
    )
    # Planned annual amount on the account's normal balance side.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    budget: Mapped["Budget"] = relationship(back_populates="lines")
    account: Mapped["GLAccount"] = relationship()


from app.models.general_ledger import GLAccount  # noqa: E402

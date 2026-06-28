from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuthLockout(Base):
    """Persistent login rate-limiting state (migration 020).

    Defined as an ORM model so ``Base.metadata.create_all`` builds the table on
    fresh-database deployments (and in the test suite), where migration-only DDL
    is otherwise skipped. The login flow reads/writes this table via raw SQL.
    """

    __tablename__ = "auth_lockouts"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

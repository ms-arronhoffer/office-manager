import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


CONSOLE_ROLES = ("super_admin", "support", "finance")


class AdminRoleAssignment(TimestampMixin, Base):
    __tablename__ = "admin_role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    console_role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

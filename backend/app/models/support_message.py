"""Support message model.

Replies that form the two-way conversation thread on a
:class:`~app.models.support_request.SupportRequest`. Each message is authored
either by the requester (or an org admin) inside the app, or by platform
support staff from the admin console (``is_from_admin`` is ``True``). The
author's name/email are snapshotted so the thread stays readable even if the
user is later removed.
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SupportMessage(TimestampMixin, Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    support_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)

    # ``True`` when the message was authored by platform support staff from the
    # admin console; ``False`` for messages from the requester or an org admin.
    is_from_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

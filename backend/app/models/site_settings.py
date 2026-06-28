from sqlalchemy import Integer, String, Text, ForeignKey, UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.models.base import Base


class SiteSettings(Base):
    __tablename__ = "site_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("organizations.id"), nullable=False)
    app_name: Mapped[str] = mapped_column(String(200), nullable=False, default="SwiftLease")
    login_subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    login_form_header: Mapped[str | None] = mapped_column(String(200), nullable=True)
    login_form_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Address that receives forwarded in-app support requests.
    support_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sla_high_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_medium_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_low_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


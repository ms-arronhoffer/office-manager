"""Custom residential application template model (Residential parity).

An :class:`ApplicationTemplate` is an org-scoped, reusable rental-application
document with ``{{merge_field}}`` placeholders plus an optional ``field_schema``
describing the structured fields an applicant fills in (income, employer,
references, prior addresses, …). Templates let staff standardise the application
they send to a prospect and drive the single-signer application e-signing engine
(:class:`~app.models.leasing_funnel.RentalApplication`): a template's rendered
body is snapshotted and hashed when an application is sent.

The body reuses the same ``{{merge_field}}`` syntax as the waiver/lease
e-signature engine (:mod:`app.services.waiver_service`), so any field returned by
the application merge context can be interpolated.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class ApplicationTemplate(SoftDeleteMixin, TimestampMixin, Base):
    """A reusable, org-scoped rental-application template with merge fields."""

    __tablename__ = "application_templates"
    __table_args__ = (
        Index("idx_application_templates_org", "organization_id"),
        Index("idx_application_templates_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Application document body carrying ``{{merge_field}}`` placeholders.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional list of structured fields the applicant fills in. Each entry is a
    # dict like ``{"key": "employer", "label": "Employer", "type": "text",
    # "required": true}``. ``type`` is one of text/textarea/number/date/select
    # (``options`` may accompany a ``select``).
    field_schema: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Marks the template offered by default when preparing an application to send.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

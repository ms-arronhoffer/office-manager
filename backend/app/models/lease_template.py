"""Custom lease template model (Residential parity).

A :class:`LeaseTemplate` is an org-scoped, reusable lease document body with
``{{merge_field}}`` placeholders. Templates let staff standardise the leases they
send to residents and drive the multi-party e-signing engine
(:class:`~app.models.leasing_funnel.LeaseSignatureRequest`): a template's rendered
body is snapshotted and hashed when a lease is sent for signature.

The body reuses the same ``{{merge_field}}`` syntax as the waiver/lease
e-signature engine (:mod:`app.services.waiver_service`), so any field returned by
the lease merge context can be interpolated.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.mixins import SoftDeleteMixin


class LeaseTemplate(SoftDeleteMixin, TimestampMixin, Base):
    """A reusable, org-scoped lease document template with merge fields."""

    __tablename__ = "lease_templates"
    __table_args__ = (
        Index("idx_lease_templates_org", "organization_id"),
        Index("idx_lease_templates_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lease document body carrying ``{{merge_field}}`` placeholders.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Marks the template offered by default when preparing a lease for signing.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

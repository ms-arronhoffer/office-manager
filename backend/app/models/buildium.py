"""Buildium migration connector — configuration, ID crosswalk, and migration
run tracking (Administration › System & Data).

Entities
--------
* :class:`BuildiumConnection`  — per-org Buildium Open API credentials
  (client id + encrypted client secret) and connection health.
* :class:`BuildiumEntityMap`   — generic ``buildium_id -> local uuid`` crosswalk
  keyed by entity type, making every migrated write idempotent (safe re-runs)
  and resolving cross-entity foreign keys (e.g. unit -> property).
* :class:`BuildiumGLAccountMap` — Buildium chart-of-accounts -> local
  :class:`~app.models.general_ledger.GLAccount` mapping, since the two systems'
  account taxonomies don't line up 1:1.
* :class:`BuildiumMigrationRun` — persisted status/progress for a single
  "Execute" invocation, polled by the admin UI's progress panel.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Entity types migrated from Buildium, in dependency order. Used both by the
# crosswalk (``BuildiumEntityMap.entity_type``) and the migration service to
# drive the run order.
BUILDIUM_ENTITY_TYPES = (
    "property",
    "unit",
    "gl_account",
    "owner",
    "owner_property",
    "vendor",
    "tenant",
    "lease",
    "lease_occupant",
    "bank_account",
    "bill",
    "gl_transaction",
    "task",
)

MIGRATION_RUN_STATUSES = ("pending", "running", "succeeded", "failed", "partial", "cancelled")


class BuildiumConnection(TimestampMixin, Base):
    """Per-organization Buildium Open API connection configuration."""

    __tablename__ = "buildium_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_buildium_connection_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Encrypted at rest — see app.utils.crypto.encrypt_secret/decrypt_secret.
    # Never returned to the client; only a masked hint is exposed.
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(
        String(255), nullable=False, default="https://api.buildium.com/v1"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verify_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_verify_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class BuildiumEntityMap(Base):
    """Crosswalk from a Buildium object id to the local row it produced."""

    __tablename__ = "buildium_entity_maps"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "entity_type", "buildium_id",
            name="uq_buildium_entity_map",
        ),
        Index("idx_buildium_entity_maps_local", "entity_type", "local_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    buildium_id: Mapped[str] = mapped_column(String(64), nullable=False)
    local_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Hash of the last-imported Buildium payload; lets a re-run skip entities
    # that haven't changed since the previous sync.
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class BuildiumGLAccountMap(TimestampMixin, Base):
    """Maps a Buildium GL account to the local chart-of-accounts entry used
    when posting migrated bills/payments/journal entries."""

    __tablename__ = "buildium_gl_account_maps"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "buildium_gl_account_id",
            name="uq_buildium_gl_account_map",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    buildium_gl_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    buildium_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buildium_account_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True
    )
    # True when ``gl_account_id`` was auto-created by the migration (as opposed
    # to an admin-chosen mapping to an existing account).
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BuildiumMigrationRun(TimestampMixin, Base):
    """A single execution of the Buildium -> Portfolio Desk migration."""

    __tablename__ = "buildium_migration_runs"
    __table_args__ = (
        Index("idx_buildium_migration_runs_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, server_default="pending"
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Ordered list of entity types requested for this run (subset of
    # BUILDIUM_ENTITY_TYPES); null/empty means "all".
    requested_entities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Per-entity-type counters: {"unit": {"created": 3, "updated": 1, "skipped": 0, "errors": []}}
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

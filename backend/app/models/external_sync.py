"""External accounting/banking connector models (QuickBooks Online + bank feed).

Two live integrations sit alongside the Buildium *migration* connector, but with
different lifecycles: these stay connected and sync incrementally rather than
running a one-shot import.

Entities
--------
* :class:`QuickBooksConnection`  — per-org QBO OAuth2 grant (realm id + encrypted
  access/refresh tokens) and the push cursor.
* :class:`QuickBooksAccountMap`  — QBO chart-of-accounts -> local
  :class:`~app.models.general_ledger.GLAccount` mapping, auto-matched on pull and
  overridable by an admin.
* :class:`QuickBooksEntrySync`   — one row per journal entry already pushed to
  QBO, keyed by a stable external reference. This is what makes a retried or
  overlapping push idempotent instead of double-posting.
* :class:`BankFeedConnection`    — per-org Plaid Item (encrypted access token)
  bound to one local :class:`~app.models.bank_account.BankAccount`, plus the
  ``/transactions/sync`` cursor.
* :class:`ExternalSyncLog`       — an audit row per sync run: cursor movement,
  counts, and any error, for the UI's "last sync" panel.

Every token column is encrypted at rest via ``app.utils.crypto``; nothing here
returns a raw token to the client.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Lifecycle of an external connection.
CONNECTION_STATUSES = ("connected", "disconnected", "error", "reauth_required")
# Connectors that write to ``ExternalSyncLog.connector``.
SYNC_CONNECTORS = ("quickbooks", "bank_feed")
# Outcome of a single sync run.
SYNC_RUN_STATUSES = ("succeeded", "failed", "partial", "skipped")

# Prefix for the stable per-entry reference sent to QBO as the DocNumber. QBO
# caps DocNumber at 21 characters, so the local uuid is truncated to its first
# 18 hex chars, which remains collision-safe within one realm.
QBO_DOC_PREFIX = "OM-"


def qbo_external_ref(journal_entry_id: uuid.UUID) -> str:
    """Stable, deterministic QBO DocNumber for a local journal entry."""
    return f"{QBO_DOC_PREFIX}{journal_entry_id.hex[:18]}"


class QuickBooksConnection(TimestampMixin, Base):
    """Per-organization QuickBooks Online OAuth2 connection."""

    __tablename__ = "quickbooks_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_quickbooks_connection_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    # QBO company id; scopes every API path.
    realm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Encrypted at rest — see app.utils.crypto. Never returned to the client.
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    environment: Mapped[str] = mapped_column(String(20), default="production", nullable=False)
    # ISO-8601 timestamp of the newest journal entry successfully pushed.
    last_sync_cursor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class QuickBooksAccountMap(TimestampMixin, Base):
    """Maps a QBO chart-of-accounts entry to a local GL account."""

    __tablename__ = "quickbooks_account_maps"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "qbo_account_id", name="uq_quickbooks_account_map"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    qbo_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    qbo_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qbo_account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qbo_account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gl_accounts.id"), nullable=True
    )
    # True once an admin picked the target explicitly; auto-matching then leaves
    # this row alone on subsequent chart pulls.
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class QuickBooksEntrySync(Base):
    """Record that a local journal entry has been pushed to QBO.

    The unique constraints are the double-post guard: a retry of the same entry
    cannot insert a second row, and the push is skipped when a row exists.
    """

    __tablename__ = "quickbooks_entry_syncs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "journal_entry_id", name="uq_quickbooks_entry_sync_entry"
        ),
        UniqueConstraint(
            "organization_id", "external_ref", name="uq_quickbooks_entry_sync_ref"
        ),
        Index("idx_quickbooks_entry_syncs_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deterministic DocNumber sent to QBO; see ``qbo_external_ref``.
    external_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    qbo_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qbo_sync_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class BankFeedConnection(TimestampMixin, Base):
    """A live bank feed (Plaid Item) bound to one local bank account."""

    __tablename__ = "bank_feed_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "bank_account_id", name="uq_bank_feed_connection_account"
        ),
        Index("idx_bank_feed_connections_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(20), default="plaid", nullable=False)
    # Encrypted at rest — see app.utils.crypto. Never returned to the client.
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    institution_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Plaid account id within the Item, when the user linked a specific account.
    provider_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    account_mask: Mapped[str | None] = mapped_column(String(8), nullable=True)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Opaque Plaid /transactions/sync cursor. NULL means "never synced".
    last_sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExternalSyncLog(Base):
    """One row per sync run, for the UI's status panel and for support triage."""

    __tablename__ = "external_sync_logs"
    __table_args__ = (
        Index("idx_external_sync_logs_org_connector", "organization_id", "connector"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    connector: Mapped[str] = mapped_column(String(30), nullable=False)
    # "push" (local -> external) or "pull" (external -> local).
    direction: Mapped[str] = mapped_column(String(10), default="push", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="succeeded", nullable=False)
    cursor_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

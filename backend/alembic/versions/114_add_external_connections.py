"""Add QuickBooks Online and bank-feed connection tables.

Revision ID: 114
Revises: 113
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None

_QBO_CONN = "quickbooks_connections"
_QBO_MAP = "quickbooks_account_maps"
_QBO_SYNC = "quickbooks_entry_syncs"
_FEED = "bank_feed_connections"
_LOG = "external_sync_logs"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if _QBO_CONN not in existing:
        op.create_table(
            _QBO_CONN,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column("realm_id", sa.String(64), nullable=False),
            # Fernet ciphertext; never stored or returned in plaintext.
            sa.Column("access_token_encrypted", sa.Text(), nullable=False),
            sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
            sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "environment", sa.String(20), nullable=False, server_default="production"
            ),
            sa.Column("last_sync_cursor", sa.String(64), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="connected"),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("organization_id", name="uq_quickbooks_connection_org"),
        )
        op.create_index(
            "idx_quickbooks_connections_org", _QBO_CONN, ["organization_id"]
        )

    if _QBO_MAP not in existing:
        op.create_table(
            _QBO_MAP,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column("qbo_account_id", sa.String(64), nullable=False),
            sa.Column("qbo_account_name", sa.String(255), nullable=True),
            sa.Column("qbo_account_type", sa.String(64), nullable=True),
            sa.Column("qbo_account_number", sa.String(64), nullable=True),
            sa.Column(
                "gl_account_id",
                UUID(as_uuid=True),
                sa.ForeignKey("gl_accounts.id"),
                nullable=True,
            ),
            sa.Column(
                "manual_override", sa.Boolean(), nullable=False, server_default="false"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "organization_id", "qbo_account_id", name="uq_quickbooks_account_map"
            ),
        )
        op.create_index("idx_quickbooks_account_maps_org", _QBO_MAP, ["organization_id"])

    if _QBO_SYNC not in existing:
        op.create_table(
            _QBO_SYNC,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column(
                "journal_entry_id",
                UUID(as_uuid=True),
                sa.ForeignKey("journal_entries.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("external_ref", sa.String(32), nullable=False),
            sa.Column("qbo_entry_id", sa.String(64), nullable=True),
            sa.Column("qbo_sync_token", sa.String(32), nullable=True),
            sa.Column(
                "synced_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            # Both constraints are the double-post guard: a concurrent or retried
            # push collides here instead of creating a second QBO JournalEntry.
            sa.UniqueConstraint(
                "organization_id",
                "journal_entry_id",
                name="uq_quickbooks_entry_sync_entry",
            ),
            sa.UniqueConstraint(
                "organization_id", "external_ref", name="uq_quickbooks_entry_sync_ref"
            ),
        )
        op.create_index("idx_quickbooks_entry_syncs_org", _QBO_SYNC, ["organization_id"])
        op.create_index(
            "idx_quickbooks_entry_syncs_entry", _QBO_SYNC, ["journal_entry_id"]
        )

    if _FEED not in existing:
        op.create_table(
            _FEED,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(20), nullable=False, server_default="plaid"),
            # Fernet ciphertext; never stored or returned in plaintext.
            sa.Column("access_token_encrypted", sa.Text(), nullable=False),
            sa.Column("item_id", sa.String(128), nullable=False),
            sa.Column("institution_name", sa.String(255), nullable=True),
            sa.Column("provider_account_id", sa.String(128), nullable=True),
            sa.Column("account_mask", sa.String(8), nullable=True),
            sa.Column(
                "bank_account_id",
                UUID(as_uuid=True),
                sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("last_sync_cursor", sa.Text(), nullable=True),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="connected"),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "organization_id",
                "bank_account_id",
                name="uq_bank_feed_connection_account",
            ),
        )
        op.create_index("idx_bank_feed_connections_org", _FEED, ["organization_id"])
        op.create_index(
            "idx_bank_feed_connections_account", _FEED, ["bank_account_id"]
        )

    if _LOG not in existing:
        op.create_table(
            _LOG,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=False,
            ),
            sa.Column("connector", sa.String(30), nullable=False),
            sa.Column("direction", sa.String(10), nullable=False, server_default="push"),
            sa.Column("status", sa.String(20), nullable=False, server_default="succeeded"),
            sa.Column("cursor_before", sa.Text(), nullable=True),
            sa.Column("cursor_after", sa.Text(), nullable=True),
            sa.Column("counts", JSONB(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_external_sync_logs_org", _LOG, ["organization_id"])
        op.create_index(
            "idx_external_sync_logs_org_connector", _LOG, ["organization_id", "connector"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in (_LOG, _FEED, _QBO_SYNC, _QBO_MAP, _QBO_CONN):
        if table in existing:
            op.drop_table(table)

"""Bank-feed sync service (Plaid -> the existing bank register).

Fetched transactions are written into the same
:class:`~app.models.bank_account.BankTransaction` rows that CSV/OFX import
produces, so the reconciliation workflow in ``app.routers.bank`` works unchanged.
The Plaid ``transaction_id`` is stored in ``fitid``, which already carries a
``(bank_account_id, fitid)`` unique constraint and is therefore the de-duplication
key for both re-imports and overlapping syncs.

Sign convention: Plaid reports a positive amount for money leaving the account,
the opposite of the register's "positive is a deposit". Amounts are negated on
import.

The ``/transactions/sync`` cursor is persisted on the connection and only
advanced after the page it describes has been committed, so an interrupted run
resumes rather than reprocessing or losing transactions.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.bank_account import BankAccount, BankTransaction
from app.models.external_sync import BankFeedConnection, ExternalSyncLog
from app.services.bank_feed import plaid_client
from app.services.bank_feed.plaid_client import PlaidApiError, PlaidClient
from app.utils.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

IMPORT_SOURCE = "plaid"
TWO = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def is_configured() -> bool:
    return plaid_client.is_configured()


def unconfigured_status() -> dict:
    """Uniform payload returned when Plaid credentials are absent."""
    return {
        "configured": False,
        "provider": "plaid",
        "detail": "Bank feed provider is not configured.",
    }


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

async def list_connections(
    db: AsyncSession, organization_id: uuid.UUID
) -> list[BankFeedConnection]:
    return list(
        (
            await db.execute(
                select(BankFeedConnection)
                .where(BankFeedConnection.organization_id == organization_id)
                .order_by(BankFeedConnection.created_at)
            )
        ).scalars().all()
    )


async def get_connection(
    db: AsyncSession, organization_id: uuid.UUID, connection_id: uuid.UUID
) -> BankFeedConnection | None:
    conn = await db.get(BankFeedConnection, connection_id)
    if conn is None or conn.organization_id != organization_id:
        return None
    return conn


async def get_connection_for_account(
    db: AsyncSession, organization_id: uuid.UUID, bank_account_id: uuid.UUID
) -> BankFeedConnection | None:
    return (
        await db.execute(
            select(BankFeedConnection).where(
                BankFeedConnection.organization_id == organization_id,
                BankFeedConnection.bank_account_id == bank_account_id,
            )
        )
    ).scalar_one_or_none()


async def store_connection(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    bank_account_id: uuid.UUID,
    access_token: str,
    item_id: str,
    institution_name: str | None = None,
    provider_account_id: str | None = None,
    account_mask: str | None = None,
    commit: bool = True,
) -> BankFeedConnection:
    """Create or replace the feed bound to a local bank account."""
    conn = await get_connection_for_account(db, organization_id, bank_account_id)
    if conn is None:
        conn = BankFeedConnection(
            organization_id=organization_id,
            bank_account_id=bank_account_id,
            access_token_encrypted="",
            item_id=item_id,
        )
        db.add(conn)
    elif conn.item_id != item_id:
        # A different Item means a different transaction stream; start over.
        conn.last_sync_cursor = None
    conn.provider = "plaid"
    conn.access_token_encrypted = encrypt_secret(access_token)
    conn.item_id = item_id
    conn.institution_name = institution_name
    conn.provider_account_id = provider_account_id
    conn.account_mask = account_mask
    conn.status = "connected"
    conn.is_enabled = True
    conn.last_error = None
    if commit:
        await db.commit()
        await db.refresh(conn)
    else:
        await db.flush()
    return conn


async def disconnect(
    db: AsyncSession, conn: BankFeedConnection, *, client: PlaidClient | None = None
) -> None:
    """Remove the Plaid Item and delete the stored grant.

    Imported transactions are deliberately kept: they may already be reconciled.
    """
    if is_configured():
        try:
            await (client or PlaidClient()).remove_item(
                decrypt_secret(conn.access_token_encrypted)
            )
        except (PlaidApiError, ValueError) as exc:
            # A dead Item on Plaid's side must not block local cleanup.
            logger.warning("Plaid item removal failed for item %s: %s", conn.item_id, exc)
    await db.delete(conn)
    await db.commit()


# ---------------------------------------------------------------------------
# Transaction sync
# ---------------------------------------------------------------------------

def _txn_date(raw: dict) -> date:
    value = raw.get("date") or raw.get("authorized_date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date()


def _description(raw: dict) -> str | None:
    name = raw.get("merchant_name") or raw.get("name")
    return str(name)[:500] if name else None


def _register_amount(raw: dict) -> Decimal:
    """Plaid positive means money out; the register's positive means deposit."""
    return _q(Decimal(str(raw.get("amount") or 0)) * -1)


def _matches_account(raw: dict, conn: BankFeedConnection) -> bool:
    if not conn.provider_account_id:
        return True
    return str(raw.get("account_id") or "") == conn.provider_account_id


async def _apply_page(
    db: AsyncSession,
    conn: BankFeedConnection,
    bank_account: BankAccount,
    page: dict,
) -> dict:
    """Apply one /transactions/sync page: added, modified, and removed."""
    added = [t for t in (page.get("added") or []) if _matches_account(t, conn)]
    modified = [t for t in (page.get("modified") or []) if _matches_account(t, conn)]
    removed = page.get("removed") or []

    incoming_ids = {
        str(t.get("transaction_id"))
        for t in added + modified
        if t.get("transaction_id")
    }
    removed_ids = {
        str(t.get("transaction_id")) for t in removed if t.get("transaction_id")
    }
    touched_ids = incoming_ids | removed_ids

    existing: dict[str, BankTransaction] = {}
    if touched_ids:
        rows = (
            await db.execute(
                select(BankTransaction).where(
                    BankTransaction.bank_account_id == bank_account.id,
                    BankTransaction.fitid.in_(touched_ids),
                )
            )
        ).scalars().all()
        existing = {row.fitid: row for row in rows if row.fitid}

    imported = updated = skipped = deleted = retained = 0

    for raw in added:
        fitid = str(raw.get("transaction_id") or "")
        if not fitid:
            skipped += 1
            continue
        if fitid in existing:
            skipped += 1
            continue
        txn = BankTransaction(
            organization_id=conn.organization_id,
            bank_account_id=bank_account.id,
            txn_date=_txn_date(raw),
            description=_description(raw),
            amount=_register_amount(raw),
            reference=(str(raw.get("payment_channel"))[:100] if raw.get("payment_channel") else None),
            fitid=fitid,
            import_source=IMPORT_SOURCE,
            status="unmatched",
        )
        db.add(txn)
        existing[fitid] = txn
        imported += 1

    for raw in modified:
        fitid = str(raw.get("transaction_id") or "")
        txn = existing.get(fitid)
        if txn is None:
            # Plaid can report a modification for a transaction we never saw.
            txn = BankTransaction(
                organization_id=conn.organization_id,
                bank_account_id=bank_account.id,
                fitid=fitid,
                import_source=IMPORT_SOURCE,
                status="unmatched",
                amount=_register_amount(raw),
                txn_date=_txn_date(raw),
            )
            db.add(txn)
            existing[fitid] = txn
            imported += 1
        elif txn.status == "cleared" or txn.reconciliation_id is not None:
            # Never mutate a line that a completed reconciliation depends on.
            retained += 1
            continue
        else:
            updated += 1
        txn.txn_date = _txn_date(raw)
        txn.description = _description(raw)
        txn.amount = _register_amount(raw)

    for raw in removed:
        fitid = str(raw.get("transaction_id") or "")
        txn = existing.get(fitid)
        if txn is None:
            continue
        if txn.status == "cleared" or txn.reconciliation_id is not None:
            retained += 1
            continue
        await db.delete(txn)
        deleted += 1

    return {
        "imported": imported,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "retained": retained,
    }


async def sync_transactions(
    db: AsyncSession,
    conn: BankFeedConnection,
    *,
    client: PlaidClient | None = None,
    max_pages: int | None = None,
) -> dict:
    """Walk /transactions/sync from the stored cursor and apply every page."""
    if not is_configured():
        return {**unconfigured_status(), "imported": 0, "updated": 0, "deleted": 0}

    bank_account = await db.get(BankAccount, conn.bank_account_id)
    if bank_account is None:
        raise PlaidApiError("The linked bank account no longer exists.")

    client = client or PlaidClient()
    max_pages = max_pages or settings.PLAID_MAX_SYNC_PAGES
    cursor_before = conn.last_sync_cursor
    log = ExternalSyncLog(
        organization_id=conn.organization_id,
        connector="bank_feed",
        direction="pull",
        cursor_before=cursor_before,
        started_at=datetime.now(timezone.utc),
    )
    db.add(log)

    totals = {"imported": 0, "updated": 0, "deleted": 0, "skipped": 0, "retained": 0, "pages": 0}
    cursor = cursor_before
    access_token = decrypt_secret(conn.access_token_encrypted)
    error: str | None = None

    try:
        for _ in range(max_pages):
            page = await client.sync_transactions(access_token, cursor)
            counts = await _apply_page(db, conn, bank_account, page)
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
            totals["pages"] += 1
            # Only advance once the page's rows are staged, so a later failure
            # resumes from this page instead of skipping it.
            cursor = page.get("next_cursor") or cursor
            if not page.get("has_more"):
                break
    except PlaidApiError as exc:
        error = str(exc)
        conn.status = "error"

    conn.last_sync_cursor = cursor
    conn.last_sync_at = datetime.now(timezone.utc)
    conn.last_error = error
    if error is None:
        conn.status = "connected"
    log.cursor_after = cursor
    log.counts = totals
    log.status = "failed" if error else "succeeded"
    log.error_message = error
    log.finished_at = datetime.now(timezone.utc)
    await db.commit()
    return {**totals, "configured": True, "cursor": cursor, "error": error}


async def recent_logs(
    db: AsyncSession, organization_id: uuid.UUID, *, limit: int = 20
) -> list[ExternalSyncLog]:
    return list(
        (
            await db.execute(
                select(ExternalSyncLog)
                .where(
                    ExternalSyncLog.organization_id == organization_id,
                    ExternalSyncLog.connector == "bank_feed",
                )
                .order_by(ExternalSyncLog.started_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )

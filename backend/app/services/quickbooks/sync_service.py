"""QuickBooks Online sync service.

Owns the two directions of the live QBO integration:

* **Push** — posted, balanced journal entries are sent to QBO as ``JournalEntry``
  objects, incrementally by cursor.
* **Pull** — the QBO chart of accounts is mirrored into
  :class:`~app.models.external_sync.QuickBooksAccountMap` and auto-matched to
  local GL accounts, leaving admin overrides untouched.

Two independent guards make a push idempotent:

1. Every local entry gets a deterministic external reference
   (:func:`~app.models.external_sync.qbo_external_ref`) used as the QBO
   ``DocNumber``. Before creating anything the client queries QBO for that
   DocNumber, so an entry that landed during a failed request is adopted rather
   than duplicated.
2. A successful push writes a :class:`~app.models.external_sync.QuickBooksEntrySync`
   row under a unique constraint on ``(organization_id, journal_entry_id)``.
   Already-synced entries are filtered out of the candidate query, and a race
   loses at the database rather than posting twice.

The cursor is only an optimisation for how far back to look; the sync table is
the authority on what has already been sent.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.external_sync import (
    ExternalSyncLog,
    QuickBooksAccountMap,
    QuickBooksConnection,
    QuickBooksEntrySync,
    qbo_external_ref,
)
from app.models.general_ledger import GLAccount, JournalEntry
from app.services.quickbooks import client as qbo_client
from app.services.quickbooks.client import (
    QuickBooksApiError,
    QuickBooksAuthError,
    QuickBooksClient,
    TokenSet,
)
from app.utils.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

# QBO account types mapped onto our five-way GL taxonomy, used when
# auto-matching a pulled QBO account to a local GL account.
_QBO_CLASSIFICATION_TO_TYPE = {
    "Asset": "asset",
    "Liability": "liability",
    "Equity": "equity",
    "Revenue": "revenue",
    "Expense": "expense",
}


class QuickBooksNotConfigured(RuntimeError):
    """Raised when the Intuit app credentials are missing."""


def is_configured() -> bool:
    return qbo_client.is_configured()


# ---------------------------------------------------------------------------
# Connection + tokens
# ---------------------------------------------------------------------------

async def get_connection(
    db: AsyncSession, organization_id: uuid.UUID
) -> QuickBooksConnection | None:
    return (
        await db.execute(
            select(QuickBooksConnection).where(
                QuickBooksConnection.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()


def _apply_tokens(conn: QuickBooksConnection, tokens: TokenSet) -> None:
    conn.access_token_encrypted = encrypt_secret(tokens.access_token)
    conn.refresh_token_encrypted = encrypt_secret(tokens.refresh_token)
    conn.access_token_expires_at = tokens.access_token_expires_at
    if tokens.refresh_token_expires_at:
        conn.refresh_token_expires_at = tokens.refresh_token_expires_at


async def store_connection(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    realm_id: str,
    tokens: TokenSet,
    commit: bool = True,
) -> QuickBooksConnection:
    """Create or replace the org's QBO connection after a successful OAuth exchange."""
    conn = await get_connection(db, organization_id)
    if conn is None:
        conn = QuickBooksConnection(
            organization_id=organization_id,
            realm_id=realm_id,
            access_token_encrypted="",
            refresh_token_encrypted="",
        )
        db.add(conn)
    # Reconnecting to a different QBO company invalidates the push history.
    if conn.realm_id and conn.realm_id != realm_id:
        conn.last_sync_cursor = None
    conn.realm_id = realm_id
    conn.environment = settings.QBO_ENVIRONMENT
    conn.status = "connected"
    conn.is_enabled = True
    conn.last_error = None
    _apply_tokens(conn, tokens)
    if commit:
        await db.commit()
        await db.refresh(conn)
    else:
        await db.flush()
    return conn


def _access_token_expired(conn: QuickBooksConnection) -> bool:
    if conn.access_token_expires_at is None:
        return True
    expires_at = conn.access_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    leeway = timedelta(seconds=settings.QBO_TOKEN_REFRESH_LEEWAY_SECONDS)
    return datetime.now(timezone.utc) + leeway >= expires_at


async def ensure_access_token(
    db: AsyncSession, conn: QuickBooksConnection, *, force: bool = False
) -> str:
    """Return a usable access token, refreshing it first when it is near expiry."""
    if not force and not _access_token_expired(conn):
        return decrypt_secret(conn.access_token_encrypted)

    refresh_token = decrypt_secret(conn.refresh_token_encrypted)
    try:
        tokens = await qbo_client.refresh_tokens(refresh_token)
    except QuickBooksApiError as exc:
        conn.status = "reauth_required"
        conn.last_error = str(exc)
        await db.commit()
        raise
    _apply_tokens(conn, tokens)
    conn.status = "connected"
    conn.last_error = None
    await db.commit()
    return tokens.access_token


async def build_client(db: AsyncSession, conn: QuickBooksConnection) -> QuickBooksClient:
    token = await ensure_access_token(db, conn)
    return QuickBooksClient(token, conn.realm_id)


async def disconnect(db: AsyncSession, conn: QuickBooksConnection) -> None:
    """Drop the stored grant. Sync history is kept so a reconnect does not re-push."""
    await db.delete(conn)
    await db.commit()


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------

def _auto_match(
    qbo_account: dict, gl_by_code: dict[str, GLAccount], gl_by_name: dict[str, GLAccount]
) -> GLAccount | None:
    """Best-effort match of a QBO account to a local GL account.

    Account number wins over name, and a name match must also agree on the
    account's high-level type so "Cash" (asset) never binds to an expense.
    """
    number = (qbo_account.get("AcctNum") or "").strip()
    if number and number in gl_by_code:
        return gl_by_code[number]
    name = (qbo_account.get("Name") or "").strip().lower()
    candidate = gl_by_name.get(name)
    if candidate is None:
        return None
    expected = _QBO_CLASSIFICATION_TO_TYPE.get(qbo_account.get("Classification") or "")
    if expected and candidate.type != expected:
        return None
    return candidate


async def pull_chart_of_accounts(
    db: AsyncSession,
    organization_id: uuid.UUID,
    client: QuickBooksClient,
) -> dict:
    """Mirror the QBO chart of accounts and auto-match unmapped rows."""
    qbo_accounts = await client.list_accounts()

    gl_accounts = (
        await db.execute(
            select(GLAccount).where(GLAccount.organization_id == organization_id)
        )
    ).scalars().all()
    gl_by_code = {a.code: a for a in gl_accounts}
    gl_by_name = {a.name.strip().lower(): a for a in gl_accounts}

    existing = {
        m.qbo_account_id: m
        for m in (
            await db.execute(
                select(QuickBooksAccountMap).where(
                    QuickBooksAccountMap.organization_id == organization_id
                )
            )
        ).scalars().all()
    }

    created = updated = matched = 0
    for account in qbo_accounts:
        qbo_id = str(account.get("Id") or "").strip()
        if not qbo_id:
            continue
        mapping = existing.get(qbo_id)
        if mapping is None:
            mapping = QuickBooksAccountMap(
                organization_id=organization_id, qbo_account_id=qbo_id
            )
            db.add(mapping)
            existing[qbo_id] = mapping
            created += 1
        else:
            updated += 1
        mapping.qbo_account_name = account.get("Name")
        mapping.qbo_account_type = account.get("AccountType") or account.get("Classification")
        mapping.qbo_account_number = account.get("AcctNum")
        # An admin's explicit choice is never overwritten by auto-matching.
        if not mapping.manual_override:
            match = _auto_match(account, gl_by_code, gl_by_name)
            if match is not None:
                mapping.gl_account_id = match.id
                matched += 1

    await db.commit()
    return {
        "pulled": len(qbo_accounts),
        "created": created,
        "updated": updated,
        "auto_matched": matched,
    }


async def gl_to_qbo_account_map(
    db: AsyncSession, organization_id: uuid.UUID
) -> dict[uuid.UUID, str]:
    """Reverse index: local GL account id -> QBO account id."""
    rows = (
        await db.execute(
            select(QuickBooksAccountMap).where(
                QuickBooksAccountMap.organization_id == organization_id,
                QuickBooksAccountMap.gl_account_id.is_not(None),
            )
        )
    ).scalars().all()
    return {row.gl_account_id: row.qbo_account_id for row in rows if row.gl_account_id}


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

def _is_balanced(entry: JournalEntry) -> bool:
    debit = sum((Decimal(str(line.debit or 0)) for line in entry.lines), Decimal("0"))
    credit = sum((Decimal(str(line.credit or 0)) for line in entry.lines), Decimal("0"))
    return bool(entry.lines) and debit == credit and debit > 0


def build_journal_entry_payload(
    entry: JournalEntry, account_map: dict[uuid.UUID, str]
) -> dict:
    """Translate a local journal entry into a QBO ``JournalEntry`` object."""
    lines = []
    for line in entry.lines:
        qbo_account_id = account_map.get(line.account_id)
        if not qbo_account_id:
            raise QuickBooksApiError(
                f"GL account {line.account_id} is not mapped to a QuickBooks account."
            )
        debit = Decimal(str(line.debit or 0))
        credit = Decimal(str(line.credit or 0))
        posting_type = "Debit" if debit > 0 else "Credit"
        amount = debit if debit > 0 else credit
        lines.append(
            {
                "DetailType": "JournalEntryLineDetail",
                "Amount": float(amount),
                "Description": (line.memo or entry.memo or "")[:4000],
                "JournalEntryLineDetail": {
                    "PostingType": posting_type,
                    "AccountRef": {"value": qbo_account_id},
                },
            }
        )
    return {
        "DocNumber": qbo_external_ref(entry.id),
        "TxnDate": entry.entry_date.isoformat(),
        "PrivateNote": (entry.memo or "")[:4000],
        "Line": lines,
    }


async def _candidate_entries(
    db: AsyncSession,
    organization_id: uuid.UUID,
    cursor: str | None,
    limit: int,
) -> list[JournalEntry]:
    """Posted entries not yet pushed, from the cursor forward.

    The cursor is inclusive (``>=``) so entries sharing a ``created_at`` with the
    last pushed one are not stranded; the already-synced subquery is what
    actually prevents reprocessing.
    """
    synced = select(QuickBooksEntrySync.journal_entry_id).where(
        QuickBooksEntrySync.organization_id == organization_id
    )
    stmt = (
        select(JournalEntry)
        .where(
            JournalEntry.organization_id == organization_id,
            JournalEntry.status == "posted",
            JournalEntry.id.not_in(synced),
        )
        .options(selectinload(JournalEntry.lines))
        .order_by(JournalEntry.created_at, JournalEntry.id)
        .limit(limit)
    )
    if cursor:
        try:
            since = datetime.fromisoformat(cursor)
        except ValueError:
            since = None
        if since is not None:
            stmt = stmt.where(JournalEntry.created_at >= since)
    return list((await db.execute(stmt)).scalars().unique().all())


def _cursor_value(entry: JournalEntry) -> str | None:
    created = entry.created_at
    return created.isoformat() if created else None


async def push_journal_entries(
    db: AsyncSession,
    organization_id: uuid.UUID,
    conn: QuickBooksConnection,
    client: QuickBooksClient,
    *,
    limit: int | None = None,
) -> dict:
    """Push not-yet-synced posted entries to QBO, advancing the cursor.

    Unbalanced or draft entries are never sent; they are counted as skipped so
    the operator can see them in the run log.
    """
    limit = limit or settings.QBO_PUSH_BATCH_LIMIT
    cursor_before = conn.last_sync_cursor
    log = ExternalSyncLog(
        organization_id=organization_id,
        connector="quickbooks",
        direction="push",
        cursor_before=cursor_before,
        started_at=datetime.now(timezone.utc),
    )
    db.add(log)

    account_map = await gl_to_qbo_account_map(db, organization_id)
    entries = await _candidate_entries(db, organization_id, cursor_before, limit)

    pushed = skipped = adopted = failed = 0
    errors: list[str] = []
    cursor_after = cursor_before

    for entry in entries:
        if entry.status != "posted" or not _is_balanced(entry):
            skipped += 1
            errors.append(f"Entry {entry.id} is not a balanced posted entry; not sent.")
            continue

        external_ref = qbo_external_ref(entry.id)
        try:
            payload = build_journal_entry_payload(entry, account_map)
        except QuickBooksApiError as exc:
            skipped += 1
            errors.append(str(exc))
            continue

        try:
            # Adopt an entry that landed in QBO during an earlier failed request.
            existing = await client.find_journal_entry_by_doc_number(external_ref)
            if existing:
                created = existing
                adopted += 1
            else:
                created = await client.create_journal_entry(payload)
                pushed += 1
        except QuickBooksApiError as exc:
            failed += 1
            errors.append(f"Entry {entry.id}: {exc}")
            break

        db.add(
            QuickBooksEntrySync(
                organization_id=organization_id,
                journal_entry_id=entry.id,
                external_ref=external_ref,
                qbo_entry_id=str(created.get("Id")) if created.get("Id") else None,
                qbo_sync_token=str(created.get("SyncToken")) if created.get("SyncToken") else None,
                synced_at=datetime.now(timezone.utc),
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            # A concurrent run already recorded this entry; its unique constraint
            # is the last line of defence against a double post.
            await db.rollback()
            skipped += 1
            continue
        cursor_after = _cursor_value(entry) or cursor_after

    counts = {
        "candidates": len(entries),
        "pushed": pushed,
        "adopted": adopted,
        "skipped": skipped,
        "failed": failed,
    }
    conn.last_sync_cursor = cursor_after
    conn.last_sync_at = datetime.now(timezone.utc)
    conn.last_error = errors[0] if failed and errors else None
    if failed:
        conn.status = "error"
    log.cursor_after = cursor_after
    log.counts = counts
    log.status = "failed" if failed else ("partial" if skipped else "succeeded")
    log.error_message = "; ".join(errors[:5]) if errors else None
    log.finished_at = datetime.now(timezone.utc)
    await db.commit()
    return {**counts, "errors": errors, "cursor": cursor_after}


async def sync_now(
    db: AsyncSession,
    organization_id: uuid.UUID,
    conn: QuickBooksConnection,
    *,
    limit: int | None = None,
) -> dict:
    """Run one push, retrying once against a refreshed token on a 401."""
    client = await build_client(db, conn)
    try:
        return await push_journal_entries(db, organization_id, conn, client, limit=limit)
    except QuickBooksAuthError:
        token = await ensure_access_token(db, conn, force=True)
        client = QuickBooksClient(token, conn.realm_id)
        return await push_journal_entries(db, organization_id, conn, client, limit=limit)


async def recent_logs(
    db: AsyncSession, organization_id: uuid.UUID, *, limit: int = 20
) -> list[ExternalSyncLog]:
    return list(
        (
            await db.execute(
                select(ExternalSyncLog)
                .where(
                    ExternalSyncLog.organization_id == organization_id,
                    ExternalSyncLog.connector == "quickbooks",
                )
                .order_by(ExternalSyncLog.started_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )

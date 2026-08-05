"""Tests for the Plaid live bank feed.

All external HTTP is mocked; nothing here touches the network. Focus areas:
graceful degradation when Plaid is unconfigured, encrypted token storage,
cursor advancement without reprocessing, and correct handling of added,
modified and removed transactions against the existing bank register.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_account import BankAccount, BankTransaction
from app.models.external_sync import BankFeedConnection, ExternalSyncLog
from app.models.general_ledger import GLAccount
from app.models.organization import Organization
from app.services.bank_feed import plaid_client
from app.services.bank_feed import sync_service as svc
from app.services.bank_feed.plaid_client import PlaidApiError, PlaidClient
from app.utils import crypto
from tests.conftest import auth_headers

FEED = "/api/v1/bank-feed"


# ─── Fakes ──────────────────────────────────────────────────────────────────

class FakePlaidClient:
    """Serves a scripted list of /transactions/sync pages and records cursors."""

    def __init__(self, pages: list[dict] | None = None):
        self.pages = pages or []
        self.calls: list[str | None] = []
        self.removed_items: list[str] = []
        self.raise_on_sync: Exception | None = None

    async def sync_transactions(self, access_token, cursor=None, *, count=500):
        self.calls.append(cursor)
        if self.raise_on_sync is not None:
            raise self.raise_on_sync
        if not self.pages:
            return {"added": [], "modified": [], "removed": [], "next_cursor": cursor, "has_more": False}
        return self.pages.pop(0)

    async def remove_item(self, access_token):
        self.removed_items.append(access_token)
        return {"removed": True}


def txn(txn_id: str, amount: str, *, name="Coffee", day="2026-03-15", account_id="acct-1"):
    """A Plaid transaction. Plaid's positive amount means money left the account."""
    return {
        "transaction_id": txn_id,
        "account_id": account_id,
        "amount": float(amount),
        "date": day,
        "name": name,
        "payment_channel": "online",
    }


def page(*, added=None, modified=None, removed=None, cursor="cursor-1", has_more=False):
    return {
        "added": added or [],
        "modified": modified or [],
        "removed": removed or [],
        "next_cursor": cursor,
        "has_more": has_more,
    }


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> Organization:
    # "pro" carries the advanced_accounting entitlement the router is gated on.
    organization = Organization(
        name="Feed Test Org", slug=f"feed-{uuid.uuid4().hex[:8]}", plan="pro"
    )
    db_session.add(organization)
    await db_session.commit()
    await db_session.refresh(organization)
    return organization


@pytest_asyncio.fixture
async def bank_account(db_session: AsyncSession, org: Organization) -> BankAccount:
    gl = GLAccount(organization_id=org.id, code="1000", name="Cash", type="asset")
    db_session.add(gl)
    await db_session.commit()
    await db_session.refresh(gl)
    account = BankAccount(
        organization_id=org.id, name="Operating", gl_account_id=gl.id, institution="Test Bank"
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def connection(
    db_session: AsyncSession, org: Organization, bank_account: BankAccount
) -> BankFeedConnection:
    return await svc.store_connection(
        db_session,
        org.id,
        bank_account_id=bank_account.id,
        access_token="access-sandbox-1",
        item_id="item-1",
        institution_name="Test Bank",
        provider_account_id="acct-1",
    )


@pytest.fixture
def plaid_on(monkeypatch):
    monkeypatch.setattr(plaid_client.settings, "PLAID_CLIENT_ID", "cid")
    monkeypatch.setattr(plaid_client.settings, "PLAID_SECRET", "secret")


@pytest.fixture
def plaid_off(monkeypatch):
    monkeypatch.setattr(plaid_client.settings, "PLAID_CLIENT_ID", "")
    monkeypatch.setattr(plaid_client.settings, "PLAID_SECRET", "")


async def _transactions(db: AsyncSession, bank_account: BankAccount) -> list[BankTransaction]:
    return list(
        (
            await db.execute(
                select(BankTransaction)
                .where(BankTransaction.bank_account_id == bank_account.id)
                .order_by(BankTransaction.txn_date, BankTransaction.fitid)
            )
        ).scalars().all()
    )


# ─── Graceful degradation ───────────────────────────────────────────────────

def test_is_configured_false_without_credentials(plaid_off):
    assert svc.is_configured() is False


def test_is_configured_true_with_credentials(plaid_on):
    assert svc.is_configured() is True


@pytest.mark.asyncio
async def test_status_unconfigured_returns_200_not_500(
    client, admin_user, org, db_session, plaid_off
):
    admin_user.organization_id = org.id
    await db_session.commit()
    resp = await client.get(f"{FEED}/status", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_link_token_unconfigured_returns_200_not_500(
    client, admin_user, org, db_session, plaid_off
):
    admin_user.organization_id = org.id
    await db_session.commit()
    resp = await client.post(f"{FEED}/link-token", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["link_token"] is None


@pytest.mark.asyncio
async def test_create_connection_unconfigured_is_503_not_500(
    client, admin_user, org, bank_account, db_session, plaid_off
):
    admin_user.organization_id = org.id
    await db_session.commit()
    resp = await client.post(
        f"{FEED}/connections",
        json={"public_token": "public-token", "bank_account_id": str(bank_account.id)},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_sync_unconfigured_degrades_without_error(db_session, connection, plaid_off):
    result = await svc.sync_transactions(db_session, connection)
    assert result["configured"] is False
    assert result["imported"] == 0


@pytest.mark.asyncio
async def test_connections_list_empty_without_provider(
    client, admin_user, org, db_session, plaid_off
):
    admin_user.organization_id = org.id
    await db_session.commit()
    resp = await client.get(f"{FEED}/connections", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json() == []


# ─── Token storage ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_access_token_encrypted_at_rest(
    db_session, org, bank_account, monkeypatch
):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    conn = await svc.store_connection(
        db_session,
        org.id,
        bank_account_id=bank_account.id,
        access_token="access-sandbox-secret",
        item_id="item-9",
    )
    assert "access-sandbox-secret" not in conn.access_token_encrypted
    assert crypto.decrypt_secret(conn.access_token_encrypted) == "access-sandbox-secret"


@pytest.mark.asyncio
async def test_relinking_a_new_item_resets_cursor(db_session, org, bank_account, connection):
    connection.last_sync_cursor = "cursor-old"
    await db_session.commit()

    conn = await svc.store_connection(
        db_session,
        org.id,
        bank_account_id=bank_account.id,
        access_token="access-2",
        item_id="item-2",
    )
    assert conn.last_sync_cursor is None


# ─── Sync behaviour ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_added_transactions_import_with_flipped_sign(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "25.50"), txn("t2", "-100.00")])])
    result = await svc.sync_transactions(db_session, connection, client=fake)

    assert result["imported"] == 2
    rows = await _transactions(db_session, bank_account)
    by_fitid = {r.fitid: r for r in rows}
    # Plaid +25.50 is money out, so the register records a withdrawal.
    assert by_fitid["t1"].amount == Decimal("-25.50")
    # Plaid -100.00 is money in, so the register records a deposit.
    assert by_fitid["t2"].amount == Decimal("100.00")
    assert by_fitid["t1"].import_source == "plaid"


@pytest.mark.asyncio
async def test_cursor_advances_and_does_not_reprocess(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="cursor-A")])
    first = await svc.sync_transactions(db_session, connection, client=fake)
    assert first["imported"] == 1
    assert connection.last_sync_cursor == "cursor-A"
    assert fake.calls == [None]

    # Second run resumes from the stored cursor and re-sends nothing.
    fake2 = FakePlaidClient([page(added=[], cursor="cursor-B")])
    second = await svc.sync_transactions(db_session, connection, client=fake2)
    assert fake2.calls == ["cursor-A"]
    assert second["imported"] == 0
    assert connection.last_sync_cursor == "cursor-B"
    assert len(await _transactions(db_session, bank_account)) == 1


@pytest.mark.asyncio
async def test_replayed_page_does_not_duplicate_transactions(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="cursor-A")])
    await svc.sync_transactions(db_session, connection, client=fake)

    # Plaid replays the same transaction (retry / overlapping window).
    replay = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="cursor-B")])
    result = await svc.sync_transactions(db_session, connection, client=replay)

    assert result["imported"] == 0
    assert result["skipped"] == 1
    assert len(await _transactions(db_session, bank_account)) == 1


@pytest.mark.asyncio
async def test_pagination_walks_until_has_more_false(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient(
        [
            page(added=[txn("t1", "10.00")], cursor="c1", has_more=True),
            page(added=[txn("t2", "20.00")], cursor="c2", has_more=True),
            page(added=[txn("t3", "30.00")], cursor="c3", has_more=False),
        ]
    )
    result = await svc.sync_transactions(db_session, connection, client=fake)
    assert result["pages"] == 3
    assert result["imported"] == 3
    assert connection.last_sync_cursor == "c3"
    assert fake.calls == [None, "c1", "c2"]


@pytest.mark.asyncio
async def test_max_pages_bounds_a_runaway_backfill(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient(
        [
            page(added=[txn("t1", "1.00")], cursor="c1", has_more=True),
            page(added=[txn("t2", "2.00")], cursor="c2", has_more=True),
            page(added=[txn("t3", "3.00")], cursor="c3", has_more=True),
        ]
    )
    result = await svc.sync_transactions(db_session, connection, client=fake, max_pages=2)
    assert result["pages"] == 2
    assert connection.last_sync_cursor == "c2"


@pytest.mark.asyncio
async def test_modified_transaction_updates_existing_row(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00", name="Pending")], cursor="c1")])
    await svc.sync_transactions(db_session, connection, client=fake)

    fake2 = FakePlaidClient(
        [page(modified=[txn("t1", "12.34", name="Settled", day="2026-03-16")], cursor="c2")]
    )
    result = await svc.sync_transactions(db_session, connection, client=fake2)

    assert result["updated"] == 1
    rows = await _transactions(db_session, bank_account)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("-12.34")
    assert rows[0].description == "Settled"


@pytest.mark.asyncio
async def test_removed_transaction_is_deleted(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="c1")])
    await svc.sync_transactions(db_session, connection, client=fake)

    fake2 = FakePlaidClient([page(removed=[{"transaction_id": "t1"}], cursor="c2")])
    result = await svc.sync_transactions(db_session, connection, client=fake2)

    assert result["deleted"] == 1
    assert await _transactions(db_session, bank_account) == []


@pytest.mark.asyncio
async def test_removed_transaction_kept_when_already_cleared(
    db_session, connection, bank_account, plaid_on
):
    """A reconciled line is never silently deleted out from under the proof."""
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="c1")])
    await svc.sync_transactions(db_session, connection, client=fake)

    rows = await _transactions(db_session, bank_account)
    rows[0].status = "cleared"
    await db_session.commit()

    fake2 = FakePlaidClient([page(removed=[{"transaction_id": "t1"}], cursor="c2")])
    result = await svc.sync_transactions(db_session, connection, client=fake2)

    assert result["deleted"] == 0
    assert result["retained"] == 1
    assert len(await _transactions(db_session, bank_account)) == 1


@pytest.mark.asyncio
async def test_modified_transaction_not_applied_to_cleared_row(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="c1")])
    await svc.sync_transactions(db_session, connection, client=fake)

    rows = await _transactions(db_session, bank_account)
    rows[0].status = "cleared"
    await db_session.commit()

    fake2 = FakePlaidClient([page(modified=[txn("t1", "99.00")], cursor="c2")])
    result = await svc.sync_transactions(db_session, connection, client=fake2)

    assert result["retained"] == 1
    rows = await _transactions(db_session, bank_account)
    assert rows[0].amount == Decimal("-10.00")


@pytest.mark.asyncio
async def test_transactions_for_other_accounts_in_item_are_ignored(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient(
        [page(added=[txn("t1", "10.00", account_id="acct-1"), txn("t2", "20.00", account_id="acct-2")])]
    )
    result = await svc.sync_transactions(db_session, connection, client=fake)
    assert result["imported"] == 1
    rows = await _transactions(db_session, bank_account)
    assert [r.fitid for r in rows] == ["t1"]


@pytest.mark.asyncio
async def test_sync_failure_records_error_and_keeps_cursor(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient()
    fake.raise_on_sync = PlaidApiError("ITEM_LOGIN_REQUIRED", error_code="ITEM_LOGIN_REQUIRED")
    result = await svc.sync_transactions(db_session, connection, client=fake)

    assert result["error"] is not None
    assert connection.status == "error"
    assert connection.last_sync_cursor is None


@pytest.mark.asyncio
async def test_sync_writes_a_log_row(db_session, connection, bank_account, plaid_on):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="c1")])
    await svc.sync_transactions(db_session, connection, client=fake)

    logs = (
        await db_session.execute(
            select(ExternalSyncLog).where(ExternalSyncLog.connector == "bank_feed")
        )
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "succeeded"
    assert logs[0].cursor_after == "c1"
    assert logs[0].counts["imported"] == 1


# ─── Disconnect ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnect_removes_item_and_keeps_transactions(
    db_session, connection, bank_account, plaid_on
):
    fake = FakePlaidClient([page(added=[txn("t1", "10.00")], cursor="c1")])
    await svc.sync_transactions(db_session, connection, client=fake)

    remover = FakePlaidClient()
    await svc.disconnect(db_session, connection, client=remover)

    assert remover.removed_items == ["access-sandbox-1"]
    assert await db_session.get(BankFeedConnection, connection.id) is None
    # Imported rows survive because they may already be reconciled.
    assert len(await _transactions(db_session, bank_account)) == 1


@pytest.mark.asyncio
async def test_disconnect_succeeds_when_provider_call_fails(
    db_session, connection, plaid_on
):
    class _Failing(FakePlaidClient):
        async def remove_item(self, access_token):
            raise PlaidApiError("item already removed")

    await svc.disconnect(db_session, connection, client=_Failing())
    assert await db_session.get(BankFeedConnection, connection.id) is None


# ─── HTTP client behaviour (mocked transport) ───────────────────────────────

class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _fake_transport(response: _FakeResponse, recorder: list | None = None):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            if recorder is not None:
                recorder.append((url, kw.get("json")))
            return response

    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_client_injects_credentials_into_body(monkeypatch, plaid_on):
    import httpx

    recorder: list = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_transport(_FakeResponse(200, {"link_token": "link-1"}), recorder),
    )
    result = await PlaidClient().create_link_token(
        client_user_id="user-1", client_name="Portfolio Desk"
    )
    assert result["link_token"] == "link-1"
    _, body = recorder[0]
    assert body["client_id"] == "cid"
    assert body["secret"] == "secret"
    assert body["products"] == ["transactions"]


@pytest.mark.asyncio
async def test_client_surfaces_plaid_error_code(monkeypatch, plaid_on):
    import httpx

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_transport(
            _FakeResponse(
                400,
                {"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "reauth needed"},
            )
        ),
    )
    with pytest.raises(PlaidApiError) as exc:
        await PlaidClient().get_accounts("access-1")
    assert exc.value.error_code == "ITEM_LOGIN_REQUIRED"


@pytest.mark.asyncio
async def test_sync_omits_cursor_on_first_call(monkeypatch, plaid_on):
    import httpx

    recorder: list = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_transport(_FakeResponse(200, {"added": [], "has_more": False}), recorder),
    )
    await PlaidClient().sync_transactions("access-1", None)
    _, body = recorder[0]
    assert "cursor" not in body


# ─── Auth gating ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_requires_authentication(client):
    resp = await client.get(f"{FEED}/connections")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_viewer_role_is_rejected(client, viewer_user):
    resp = await client.get(f"{FEED}/connections", headers=auth_headers(viewer_user))
    assert resp.status_code == 403

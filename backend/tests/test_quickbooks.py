"""Tests for the QuickBooks Online connector.

All external HTTP is mocked; nothing here touches the network. Focus areas:
token encryption at rest, refresh-on-expiry, cursor advancement without
reprocessing, and suppression of duplicate pushes.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_sync import (
    QuickBooksAccountMap,
    QuickBooksConnection,
    QuickBooksEntrySync,
    qbo_external_ref,
)
from app.models.general_ledger import GLAccount
from app.models.organization import Organization
from app.services import gl_service
from app.services.quickbooks import client as qbo_client
from app.services.quickbooks import sync_service as svc
from app.services.quickbooks.client import (
    QuickBooksApiError,
    QuickBooksAuthError,
    QuickBooksClient,
    TokenSet,
)
from app.utils import crypto
from tests.conftest import auth_headers

QBO = "/api/v1/quickbooks"


# ─── Fakes ──────────────────────────────────────────────────────────────────

class FakeQboClient:
    """Stand-in for :class:`QuickBooksClient` that records every call."""

    def __init__(self, *, existing_doc_numbers: set[str] | None = None):
        self.existing = existing_doc_numbers or set()
        self.created: list[dict] = []
        self.lookups: list[str] = []
        self.accounts: list[dict] = []
        self.raise_auth_error_once = False
        self._auth_error_raised = False

    async def find_journal_entry_by_doc_number(self, doc_number: str):
        self.lookups.append(doc_number)
        if doc_number in self.existing:
            return {"Id": f"qbo-{doc_number}", "SyncToken": "0"}
        return None

    async def create_journal_entry(self, payload: dict):
        if self.raise_auth_error_once and not self._auth_error_raised:
            self._auth_error_raised = True
            raise QuickBooksAuthError("token expired", status_code=401)
        self.created.append(payload)
        doc = payload.get("DocNumber")
        self.existing.add(doc)
        return {"Id": f"qbo-{doc}", "SyncToken": "0"}

    async def list_accounts(self):
        return self.accounts


def make_tokens(*, access="access-1", refresh="refresh-1", ttl_seconds=3600) -> TokenSet:
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        refresh_token_expires_at=datetime.now(timezone.utc) + timedelta(days=100),
    )


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> Organization:
    # "pro" carries the advanced_accounting entitlement the router is gated on.
    organization = Organization(
        name="QBO Test Org", slug=f"qbo-{uuid.uuid4().hex[:8]}", plan="pro"
    )
    db_session.add(organization)
    await db_session.commit()
    await db_session.refresh(organization)
    return organization


@pytest_asyncio.fixture
async def accounts(db_session: AsyncSession, org: Organization) -> list[GLAccount]:
    created = []
    for code, name, type_ in (("1000", "Cash", "asset"), ("4000", "Rental Income", "revenue")):
        account = GLAccount(organization_id=org.id, code=code, name=name, type=type_)
        db_session.add(account)
        created.append(account)
    await db_session.commit()
    for account in created:
        await db_session.refresh(account)
    return created


@pytest_asyncio.fixture
async def connection(db_session: AsyncSession, org: Organization) -> QuickBooksConnection:
    return await svc.store_connection(
        db_session, org.id, realm_id="realm-123", tokens=make_tokens()
    )


async def _make_entry(
    db: AsyncSession, org: Organization, accounts: list[GLAccount], amount: str = "100.00"
):
    cash, income = accounts
    return await gl_service.create_journal_entry(
        db,
        org.id,
        entry_date=date(2026, 3, 15),
        lines=[
            {"account_id": cash.id, "debit": Decimal(amount)},
            {"account_id": income.id, "credit": Decimal(amount)},
        ],
        memo="Rent received",
    )


async def _map_accounts(db: AsyncSession, org: Organization, accounts: list[GLAccount]) -> None:
    for idx, account in enumerate(accounts, start=1):
        db.add(
            QuickBooksAccountMap(
                organization_id=org.id,
                qbo_account_id=str(idx),
                qbo_account_name=account.name,
                gl_account_id=account.id,
            )
        )
    await db.commit()


# ─── Configuration degradation ──────────────────────────────────────────────

def test_is_configured_false_without_credentials(monkeypatch):
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_ID", "")
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_SECRET", "")
    assert svc.is_configured() is False


def test_is_configured_true_with_credentials(monkeypatch):
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_ID", "cid")
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_SECRET", "secret")
    assert svc.is_configured() is True


@pytest.mark.asyncio
async def test_authorize_url_unconfigured_returns_200_not_500(
    client, admin_user, monkeypatch, org, db_session
):
    """An unconfigured provider degrades gracefully instead of erroring."""
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_ID", "")
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_SECRET", "")
    admin_user.organization_id = org.id
    await db_session.commit()

    resp = await client.get(f"{QBO}/authorize-url", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["authorize_url"] is None


@pytest.mark.asyncio
async def test_connection_status_unconnected(client, admin_user, org, db_session):
    admin_user.organization_id = org.id
    await db_session.commit()
    resp = await client.get(f"{QBO}/connection", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


@pytest.mark.asyncio
async def test_sync_without_connection_is_400_not_500(client, admin_user, org, db_session):
    admin_user.organization_id = org.id
    await db_session.commit()
    resp = await client.post(f"{QBO}/sync", json={}, headers=auth_headers(admin_user))
    assert resp.status_code == 400


# ─── Token storage and refresh ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tokens_are_encrypted_at_rest(db_session: AsyncSession, org: Organization, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    conn = await svc.store_connection(
        db_session,
        org.id,
        realm_id="realm-1",
        tokens=make_tokens(access="plain-access", refresh="plain-refresh"),
    )
    assert "plain-access" not in conn.access_token_encrypted
    assert "plain-refresh" not in conn.refresh_token_encrypted
    assert crypto.decrypt_secret(conn.access_token_encrypted) == "plain-access"
    assert crypto.decrypt_secret(conn.refresh_token_encrypted) == "plain-refresh"


@pytest.mark.asyncio
async def test_access_token_reused_while_valid(db_session, connection, monkeypatch):
    async def _fail_refresh(_token):
        raise AssertionError("refresh must not be called while the token is valid")

    monkeypatch.setattr(qbo_client, "refresh_tokens", _fail_refresh)
    token = await svc.ensure_access_token(db_session, connection)
    assert token == "access-1"


@pytest.mark.asyncio
async def test_expired_access_token_triggers_refresh(db_session, connection, monkeypatch):
    calls = {"n": 0}

    async def _refresh(refresh_token):
        calls["n"] += 1
        assert refresh_token == "refresh-1"
        return make_tokens(access="access-2", refresh="refresh-2")

    monkeypatch.setattr(qbo_client, "refresh_tokens", _refresh)
    connection.access_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()

    token = await svc.ensure_access_token(db_session, connection)
    assert token == "access-2"
    assert calls["n"] == 1
    # The rotated refresh token must replace the stored one.
    assert crypto.decrypt_secret(connection.refresh_token_encrypted) == "refresh-2"


@pytest.mark.asyncio
async def test_failed_refresh_marks_connection_reauth_required(db_session, connection, monkeypatch):
    async def _refresh(_token):
        raise QuickBooksApiError("refresh token revoked", status_code=400)

    monkeypatch.setattr(qbo_client, "refresh_tokens", _refresh)
    connection.access_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()

    with pytest.raises(QuickBooksApiError):
        await svc.ensure_access_token(db_session, connection)
    assert connection.status == "reauth_required"


# ─── Payload construction ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payload_uses_stable_external_ref_and_balanced_lines(
    db_session, org, accounts
):
    entry = await _make_entry(db_session, org, accounts)
    account_map = {accounts[0].id: "10", accounts[1].id: "40"}
    payload = svc.build_journal_entry_payload(entry, account_map)

    assert payload["DocNumber"] == qbo_external_ref(entry.id)
    assert len(payload["Line"]) == 2
    postings = {line["JournalEntryLineDetail"]["PostingType"] for line in payload["Line"]}
    assert postings == {"Debit", "Credit"}
    assert sum(line["Amount"] for line in payload["Line"]) == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_payload_rejects_unmapped_account(db_session, org, accounts):
    entry = await _make_entry(db_session, org, accounts)
    with pytest.raises(QuickBooksApiError):
        svc.build_journal_entry_payload(entry, {})


@pytest.mark.asyncio
async def test_unbalanced_entry_is_not_pushed(db_session, org, accounts, connection):
    await _map_accounts(db_session, org, accounts)
    entry = await _make_entry(db_session, org, accounts)
    # Corrupt the entry after creation; the guard must still catch it.
    entry.lines[0].debit = Decimal("999.00")
    await db_session.commit()

    fake = FakeQboClient()
    result = await svc.push_journal_entries(db_session, org.id, connection, fake)
    assert result["pushed"] == 0
    assert result["skipped"] == 1
    assert fake.created == []


@pytest.mark.asyncio
async def test_draft_entry_is_not_pushed(db_session, org, accounts, connection):
    await _map_accounts(db_session, org, accounts)
    entry = await _make_entry(db_session, org, accounts)
    entry.status = "draft"
    await db_session.commit()

    fake = FakeQboClient()
    result = await svc.push_journal_entries(db_session, org.id, connection, fake)
    assert result["pushed"] == 0
    assert fake.created == []


# ─── Cursor + duplicate suppression ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_advances_cursor_and_does_not_reprocess(
    db_session, org, accounts, connection
):
    await _map_accounts(db_session, org, accounts)
    await _make_entry(db_session, org, accounts, "100.00")
    await _make_entry(db_session, org, accounts, "250.00")

    fake = FakeQboClient()
    first = await svc.push_journal_entries(db_session, org.id, connection, fake)
    assert first["pushed"] == 2
    assert first["cursor"] is not None
    assert connection.last_sync_cursor == first["cursor"]

    # A second run over the same data must be a no-op.
    second = await svc.push_journal_entries(db_session, org.id, connection, fake)
    assert second["candidates"] == 0
    assert second["pushed"] == 0
    assert len(fake.created) == 2


@pytest.mark.asyncio
async def test_only_new_entries_push_after_cursor_advance(
    db_session, org, accounts, connection
):
    await _map_accounts(db_session, org, accounts)
    await _make_entry(db_session, org, accounts, "100.00")

    fake = FakeQboClient()
    await svc.push_journal_entries(db_session, org.id, connection, fake)
    assert len(fake.created) == 1

    await _make_entry(db_session, org, accounts, "300.00")
    result = await svc.push_journal_entries(db_session, org.id, connection, fake)
    assert result["pushed"] == 1
    assert len(fake.created) == 2


@pytest.mark.asyncio
async def test_duplicate_push_suppressed_by_sync_record(
    db_session, org, accounts, connection
):
    await _map_accounts(db_session, org, accounts)
    entry = await _make_entry(db_session, org, accounts)

    fake = FakeQboClient()
    await svc.push_journal_entries(db_session, org.id, connection, fake)

    # Rewinding the cursor must not resend an entry already recorded as synced.
    connection.last_sync_cursor = None
    await db_session.commit()
    result = await svc.push_journal_entries(db_session, org.id, connection, fake)

    assert result["pushed"] == 0
    assert len(fake.created) == 1
    syncs = (
        await db_session.execute(
            select(QuickBooksEntrySync).where(
                QuickBooksEntrySync.journal_entry_id == entry.id
            )
        )
    ).scalars().all()
    assert len(syncs) == 1


@pytest.mark.asyncio
async def test_retry_adopts_entry_already_present_in_qbo(
    db_session, org, accounts, connection
):
    """A push that landed in QBO before the response was lost is adopted, not duplicated."""
    await _map_accounts(db_session, org, accounts)
    entry = await _make_entry(db_session, org, accounts)

    fake = FakeQboClient(existing_doc_numbers={qbo_external_ref(entry.id)})
    result = await svc.push_journal_entries(db_session, org.id, connection, fake)

    assert result["pushed"] == 0
    assert result["adopted"] == 1
    assert fake.created == []
    sync = (
        await db_session.execute(
            select(QuickBooksEntrySync).where(
                QuickBooksEntrySync.journal_entry_id == entry.id
            )
        )
    ).scalar_one()
    assert sync.external_ref == qbo_external_ref(entry.id)


@pytest.mark.asyncio
async def test_sync_now_retries_once_after_401(db_session, org, accounts, connection, monkeypatch):
    await _map_accounts(db_session, org, accounts)
    await _make_entry(db_session, org, accounts)

    fake = FakeQboClient()
    fake.raise_auth_error_once = True
    refreshed = {"n": 0}

    async def _refresh(_token):
        refreshed["n"] += 1
        return make_tokens(access="access-2", refresh="refresh-2")

    monkeypatch.setattr(qbo_client, "refresh_tokens", _refresh)
    monkeypatch.setattr(svc, "build_client", lambda db, conn: _async_value(fake))
    monkeypatch.setattr(svc, "QuickBooksClient", lambda token, realm: fake)

    result = await svc.sync_now(db_session, org.id, connection)
    assert refreshed["n"] == 1
    assert result["pushed"] == 1


async def _async_value(value):
    return value


# ─── Chart of accounts ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pull_chart_of_accounts_auto_matches_by_number(db_session, org, accounts):
    fake = FakeQboClient()
    fake.accounts = [
        {"Id": "77", "Name": "Operating Cash", "AcctNum": "1000", "Classification": "Asset"},
    ]
    result = await svc.pull_chart_of_accounts(db_session, org.id, fake)
    assert result["created"] == 1
    assert result["auto_matched"] == 1

    mapping = (
        await db_session.execute(
            select(QuickBooksAccountMap).where(QuickBooksAccountMap.qbo_account_id == "77")
        )
    ).scalar_one()
    assert mapping.gl_account_id == accounts[0].id


@pytest.mark.asyncio
async def test_pull_does_not_override_manual_mapping(db_session, org, accounts):
    db_session.add(
        QuickBooksAccountMap(
            organization_id=org.id,
            qbo_account_id="77",
            gl_account_id=accounts[1].id,
            manual_override=True,
        )
    )
    await db_session.commit()

    fake = FakeQboClient()
    fake.accounts = [
        {"Id": "77", "Name": "Operating Cash", "AcctNum": "1000", "Classification": "Asset"},
    ]
    await svc.pull_chart_of_accounts(db_session, org.id, fake)

    mapping = (
        await db_session.execute(
            select(QuickBooksAccountMap).where(QuickBooksAccountMap.qbo_account_id == "77")
        )
    ).scalar_one()
    assert mapping.gl_account_id == accounts[1].id


@pytest.mark.asyncio
async def test_auto_match_rejects_name_match_with_wrong_type(db_session, org, accounts):
    fake = FakeQboClient()
    fake.accounts = [{"Id": "88", "Name": "Cash", "Classification": "Expense"}]
    result = await svc.pull_chart_of_accounts(db_session, org.id, fake)
    assert result["auto_matched"] == 0


# ─── HTTP client behaviour (mocked transport) ───────────────────────────────

class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = str(json_data)

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _fake_transport(responses: list[_FakeResponse], recorder: list | None = None):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            if recorder is not None:
                recorder.append((method, url, kw))
            return responses.pop(0) if len(responses) > 1 else responses[0]

        async def post(self, url, **kw):
            if recorder is not None:
                recorder.append(("POST", url, kw))
            return responses.pop(0) if len(responses) > 1 else responses[0]

    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_client_raises_auth_error_on_401(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _fake_transport([_FakeResponse(401, {})]))
    client = QuickBooksClient("token", "realm", max_retries=0, retry_base_seconds=0)
    with pytest.raises(QuickBooksAuthError):
        await client.query("SELECT * FROM Account")


@pytest.mark.asyncio
async def test_client_retries_on_429_then_succeeds(monkeypatch):
    import httpx

    responses = [
        _FakeResponse(429, {}, headers={"Retry-After": "0"}),
        _FakeResponse(200, {"QueryResponse": {"Account": [{"Id": "1"}]}}),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _fake_transport(responses))
    client = QuickBooksClient("token", "realm", max_retries=2, retry_base_seconds=0)
    result = await client.query("SELECT * FROM Account")
    assert result["Account"] == [{"Id": "1"}]


@pytest.mark.asyncio
async def test_list_accounts_follows_qbo_start_position_pagination(monkeypatch):
    import httpx

    first_page = [{"Id": str(index)} for index in range(100)]
    recorder: list = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_transport(
            [
                _FakeResponse(200, {"QueryResponse": {"Account": first_page}}),
                _FakeResponse(200, {"QueryResponse": {"Account": [{"Id": "last"}]}}),
            ],
            recorder,
        ),
    )
    client = QuickBooksClient("token", "realm", max_retries=0)
    accounts = await client.list_accounts()
    assert len(accounts) == 101
    assert "STARTPOSITION 1 MAXRESULTS 100" in recorder[0][2]["params"]["query"]
    assert "STARTPOSITION 101 MAXRESULTS 100" in recorder[1][2]["params"]["query"]


@pytest.mark.asyncio
async def test_refresh_tokens_rotates_refresh_token(monkeypatch):
    import httpx

    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_ID", "cid")
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_transport(
            [
                _FakeResponse(
                    200,
                    {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                        "x_refresh_token_expires_in": 8726400,
                    },
                )
            ]
        ),
    )
    tokens = await qbo_client.refresh_tokens("old-refresh")
    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"


@pytest.mark.asyncio
async def test_refresh_tokens_keeps_old_refresh_when_absent(monkeypatch):
    import httpx

    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_ID", "cid")
    monkeypatch.setattr(qbo_client.settings, "QBO_CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_transport([_FakeResponse(200, {"access_token": "a", "expires_in": 3600})]),
    )
    tokens = await qbo_client.refresh_tokens("old-refresh")
    assert tokens.refresh_token == "old-refresh"


# ─── Auth gating ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_requires_authentication(client):
    resp = await client.get(f"{QBO}/connection")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_viewer_role_is_rejected(client, viewer_user):
    resp = await client.get(f"{QBO}/connection", headers=auth_headers(viewer_user))
    assert resp.status_code == 403

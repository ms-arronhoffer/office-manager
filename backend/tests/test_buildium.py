"""Tests for the Buildium migration connector: encryption, the HTTP client's
retry/pagination behavior, the migration service's idempotent upserts, and the
``/api/v1/buildium`` router's auth gating and connection lifecycle.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buildium import BuildiumConnection, BuildiumEntityMap
from app.models.office import Office
from app.models.organization import Organization
from app.models.resident import RentalUnit
from app.services.buildium.client import BuildiumApiError, BuildiumClient
from app.services.buildium import migration_service as ms
from app.utils import crypto
from tests.conftest import auth_headers

BUILDIUM = "/api/v1/buildium"


# ─── Encryption ─────────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    token = crypto.encrypt_secret("super-secret-value")
    assert token != "super-secret-value"
    assert crypto.decrypt_secret(token) == "super-secret-value"


def test_encrypt_without_key_degrades_but_round_trips(monkeypatch):
    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", "")
    token = crypto.encrypt_secret("plain-secret")
    assert crypto.decrypt_secret(token) == "plain-secret"


def test_mask_secret():
    assert crypto.mask_secret("abcd1234efgh").endswith("efgh")
    assert crypto.mask_secret("") == ""


# ─── BuildiumClient retry/pagination ────────────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = str(json_data)

    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_client_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(429, headers={"Retry-After": "0"})
            return _FakeResponse(200, json_data=[{"Id": 1}])

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = BuildiumClient("cid", "secret", max_retries=2, retry_base_seconds=0)
    result = await client.get("rentals")
    assert result == [{"Id": 1}]
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_client_raises_after_exhausting_retries(monkeypatch):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            return _FakeResponse(500)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = BuildiumClient("cid", "secret", max_retries=1, retry_base_seconds=0)
    with pytest.raises(BuildiumApiError):
        await client.get("rentals")


@pytest.mark.asyncio
async def test_client_non_retryable_error_raises_immediately(monkeypatch):
    calls = {"n": 0}

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            calls["n"] += 1
            return _FakeResponse(403, json_data={"Message": "forbidden"})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = BuildiumClient("cid", "secret", max_retries=3, retry_base_seconds=0)
    with pytest.raises(BuildiumApiError):
        await client.get("rentals")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_client_paginates_until_short_page(monkeypatch):
    pages = [[{"Id": i} for i in range(100)], [{"Id": 100}]]

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, params=None, **kw):
            offset = params["offset"]
            page = pages[offset // 100]
            return _FakeResponse(200, json_data=page)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = BuildiumClient("cid", "secret", page_size=100)
    items = [item async for item in client.paginate("rentals")]
    assert len(items) == 101


@pytest.mark.asyncio
async def test_client_test_connection_reports_failure(monkeypatch):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            return _FakeResponse(401, json_data={"Message": "bad creds"})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = BuildiumClient("cid", "secret", max_retries=0)
    ok, error = await client.test_connection()
    assert ok is False
    assert error is not None


# ─── Migration service: idempotent upserts ─────────────────────────────────

class _FakeBuildiumClient:
    """Duck-typed stand-in for BuildiumClient exposing only what migrators use."""

    def __init__(self, properties=None, units_by_property=None):
        self._properties = properties or []
        self._units = units_by_property or {}

    async def list_properties(self):
        for item in self._properties:
            yield item

    async def list_units(self, property_id):
        for item in self._units.get(property_id, []):
            yield item


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> uuid.UUID:
    o = Organization(id=uuid.uuid4(), name="Test Org", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.commit()
    return o.id


@pytest.mark.asyncio
async def test_migrate_properties_creates_then_updates(db_session: AsyncSession, org):
    client = _FakeBuildiumClient(properties=[
        {"Id": 501, "Name": "Sunset Apartments", "IsActive": True,
         "Address": {"AddressLine1": "1 Main St", "City": "Austin", "State": "TX", "PostalCode": "78701"}},
    ])
    result = await ms.migrate_properties(db_session, org, client, dry_run=False)
    assert result.created == 1
    assert result.errors == []

    offices = (await db_session.execute(select(Office).where(Office.organization_id == org))).scalars().all()
    assert len(offices) == 1
    assert offices[0].location_name == "Sunset Apartments"

    # Re-run with an updated name — should update, not duplicate.
    client2 = _FakeBuildiumClient(properties=[
        {"Id": 501, "Name": "Sunset Apartments Renamed", "IsActive": True, "Address": {}},
    ])
    result2 = await ms.migrate_properties(db_session, org, client2, dry_run=False)
    assert result2.updated == 1
    assert result2.created == 0

    offices = (await db_session.execute(select(Office).where(Office.organization_id == org))).scalars().all()
    assert len(offices) == 1
    assert offices[0].location_name == "Sunset Apartments Renamed"

    maps = (
        await db_session.execute(
            select(BuildiumEntityMap).where(
                BuildiumEntityMap.organization_id == org, BuildiumEntityMap.entity_type == "property"
            )
        )
    ).scalars().all()
    assert len(maps) == 1


@pytest.mark.asyncio
async def test_migrate_properties_dry_run_does_not_persist(db_session: AsyncSession, org):
    client = _FakeBuildiumClient(properties=[
        {"Id": 900, "Name": "Dry Run Property", "IsActive": True, "Address": {}},
    ])
    result = await ms.migrate_properties(db_session, org, client, dry_run=True)
    assert result.created == 1

    offices = (await db_session.execute(select(Office).where(Office.organization_id == org))).scalars().all()
    assert len(offices) == 0
    maps = (
        await db_session.execute(
            select(BuildiumEntityMap).where(BuildiumEntityMap.organization_id == org)
        )
    ).scalars().all()
    assert len(maps) == 0


@pytest.mark.asyncio
async def test_migrate_units_resolves_property_crosswalk(db_session: AsyncSession, org):
    prop_client = _FakeBuildiumClient(properties=[{"Id": 1, "Name": "P1", "IsActive": True, "Address": {}}])
    await ms.migrate_properties(db_session, org, prop_client, dry_run=False)

    unit_client = _FakeBuildiumClient(units_by_property={
        "1": [{"Id": 10, "UnitNumber": "101", "MarketRent": "1500.00", "UnitBedrooms": 2}],
    })
    result = await ms.migrate_units(db_session, org, unit_client, dry_run=False)
    assert result.created == 1
    assert result.errors == []

    units = (await db_session.execute(select(RentalUnit).where(RentalUnit.organization_id == org))).scalars().all()
    assert len(units) == 1
    assert units[0].unit_number == "101"
    assert units[0].market_rent == Decimal("1500.00")


@pytest.mark.asyncio
async def test_migrate_leases_skips_when_unit_not_migrated(db_session: AsyncSession, org):
    class _LeaseClient(_FakeBuildiumClient):
        async def list_leases(self):
            yield {"Id": 1, "UnitId": 999, "LeaseFromDate": "2026-01-01", "RentAmount": "1000"}

    lease_result, occupant_result = await ms.migrate_leases(db_session, org, _LeaseClient(), dry_run=False)
    assert lease_result.created == 0
    assert len(lease_result.errors) == 1
    assert "not migrated yet" in lease_result.errors[0]


# ─── Router: connection lifecycle + auth gating ────────────────────────────

@pytest_asyncio.fixture
async def org_admin(db_session: AsyncSession, admin_user, org):
    admin_user.organization_id = org
    await db_session.commit()
    return admin_user


@pytest_asyncio.fixture
async def org_viewer(db_session: AsyncSession, viewer_user, org):
    viewer_user.organization_id = org
    await db_session.commit()
    return viewer_user


@pytest.mark.asyncio
async def test_viewer_forbidden_from_connection(client, org_viewer):
    resp = await client.get(f"{BUILDIUM}/connection", headers=auth_headers(org_viewer))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_without_org_gets_403(client, admin_user):
    resp = await client.get(f"{BUILDIUM}/connection", headers=auth_headers(admin_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_save_and_get_connection_never_returns_secret(client, org_admin):
    resp = await client.get(f"{BUILDIUM}/connection", headers=auth_headers(org_admin))
    assert resp.status_code == 200
    assert resp.json()["configured"] is False

    save = await client.put(
        f"{BUILDIUM}/connection",
        json={"client_id": "abc123", "client_secret": "topsecretvalue"},
        headers=auth_headers(org_admin),
    )
    assert save.status_code == 200
    body = save.json()
    assert body["configured"] is True
    assert body["client_id"] == "abc123"
    assert "topsecretvalue" not in str(body)
    assert body["client_secret_hint"].endswith("alue")


@pytest.mark.asyncio
async def test_connection_encrypted_at_rest(db_session: AsyncSession, client, org_admin, monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import crypto as crypto_module

    monkeypatch.setattr(crypto_module.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    await client.put(
        f"{BUILDIUM}/connection",
        json={"client_id": "abc123", "client_secret": "topsecretvalue"},
        headers=auth_headers(org_admin),
    )
    conn = (
        await db_session.execute(
            select(BuildiumConnection).where(BuildiumConnection.organization_id == org_admin.organization_id)
        )
    ).scalar_one()
    assert "topsecretvalue" not in conn.client_secret_encrypted


@pytest.mark.asyncio
async def test_test_connection_requires_saved_connection(client, org_admin):
    resp = await client.post(f"{BUILDIUM}/connection/test", headers=auth_headers(org_admin))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_test_connection_uses_client(client, org_admin, monkeypatch):
    await client.put(
        f"{BUILDIUM}/connection",
        json={"client_id": "abc123", "client_secret": "topsecretvalue"},
        headers=auth_headers(org_admin),
    )

    async def _fake_test_connection(self):
        return True, None

    monkeypatch.setattr(BuildiumClient, "test_connection", _fake_test_connection)
    resp = await client.post(f"{BUILDIUM}/connection/test", headers=auth_headers(org_admin))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "error": None}


@pytest.mark.asyncio
async def test_start_migration_requires_connection(client, org_admin):
    resp = await client.post(f"{BUILDIUM}/migrate", json={}, headers=auth_headers(org_admin))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_migration_rejects_unknown_entity(client, org_admin):
    await client.put(
        f"{BUILDIUM}/connection",
        json={"client_id": "abc123", "client_secret": "topsecretvalue"},
        headers=auth_headers(org_admin),
    )
    resp = await client.post(
        f"{BUILDIUM}/migrate", json={"entities": ["not_a_real_entity"]}, headers=auth_headers(org_admin)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_migration_returns_pending_run(client, org_admin, monkeypatch):
    import app.routers.buildium as buildium_router

    async def _fake_run_migration(db, organization_id, client_, *, entities, dry_run, actor_id, on_progress):
        return {}

    # Avoid the background task making a real network call to Buildium.
    monkeypatch.setattr(buildium_router, "run_migration", _fake_run_migration)

    await client.put(
        f"{BUILDIUM}/connection",
        json={"client_id": "abc123", "client_secret": "topsecretvalue"},
        headers=auth_headers(org_admin),
    )
    resp = await client.post(
        f"{BUILDIUM}/migrate", json={"entities": ["property"], "dry_run": True},
        headers=auth_headers(org_admin),
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["dry_run"] is True

    listed = await client.get(f"{BUILDIUM}/runs", headers=auth_headers(org_admin))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_entities_endpoint_lists_migratable_types(client, org_admin):
    resp = await client.get(f"{BUILDIUM}/entities", headers=auth_headers(org_admin))
    assert resp.status_code == 200
    keys = {row["key"] for row in resp.json()}
    assert "property" in keys
    assert "lease" in keys

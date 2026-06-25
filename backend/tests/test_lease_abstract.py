import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease
from app.services.lease_abstract_catalog import CLAUSE_CATEGORIES
from tests.conftest import auth_headers


@pytest_asyncio.fixture
async def abstract_lease(db_session: AsyncSession, admin_user) -> Lease:
    lease = Lease(
        id=uuid.uuid4(),
        organization_id=admin_user.organization_id,
        lease_name="Abstract Test Lease",
        expiration_year=2030,
    )
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


@pytest.mark.asyncio
async def test_get_abstract_returns_full_catalog(client, admin_user, abstract_lease):
    resp = await client.get(
        f"/api/v1/leases/{abstract_lease.id}/abstract", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clauses"]) == len(CLAUSE_CATEGORIES)
    # Every clause defaults to needs_content with no stored content.
    assert all(c["status"] == "needs_content" for c in data["clauses"])
    assert data["summary"]["total"] == len(CLAUSE_CATEGORIES)
    assert data["summary"]["needs_content"] == len(CLAUSE_CATEGORIES)
    # Catalog metadata is present on each clause.
    sd = next(c for c in data["clauses"] if c["category_key"] == "security_deposit")
    assert sd["name"] == "Security Deposit"
    assert any(f["key"] == "deposit_amount" for f in sd["fields"])


@pytest.mark.asyncio
async def test_abstract_404_for_unknown_lease(client, admin_user):
    resp = await client.get(
        f"/api/v1/leases/{uuid.uuid4()}/abstract", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upsert_partial_content_marks_incomplete(client, admin_user, abstract_lease):
    resp = await client.put(
        f"/api/v1/leases/{abstract_lease.id}/abstract/security_deposit",
        headers=auth_headers(admin_user),
        json={"content": {"deposit_amount": 5000}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "incomplete"
    assert body["content"]["deposit_amount"] == 5000


@pytest.mark.asyncio
async def test_upsert_full_content_marks_contains_content(client, admin_user, abstract_lease):
    cat = next(c for c in CLAUSE_CATEGORIES if c["key"] == "interest")
    content = {f["key"]: "x" for f in cat["fields"]}
    resp = await client.put(
        f"/api/v1/leases/{abstract_lease.id}/abstract/interest",
        headers=auth_headers(admin_user),
        json={"content": content},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "contains_content"


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_reflected_in_summary(client, admin_user, abstract_lease):
    headers = auth_headers(admin_user)
    url = f"/api/v1/leases/{abstract_lease.id}/abstract/holdover"
    await client.put(url, headers=headers, json={"content": {"holdover_rate": 1.5}})
    # Update again — should remain a single row.
    await client.put(url, headers=headers, json={"content": {"holdover_rate": 2.0}})

    resp = await client.get(
        f"/api/v1/leases/{abstract_lease.id}/abstract", headers=headers
    )
    clause = next(c for c in resp.json()["clauses"] if c["category_key"] == "holdover")
    assert clause["content"]["holdover_rate"] == 2.0
    assert resp.json()["summary"]["incomplete"] == 1


@pytest.mark.asyncio
async def test_explicit_status_override(client, admin_user, abstract_lease):
    resp = await client.put(
        f"/api/v1/leases/{abstract_lease.id}/abstract/notices",
        headers=auth_headers(admin_user),
        json={"notes": "N/A", "status": "contains_content"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "contains_content"


@pytest.mark.asyncio
async def test_upsert_rejects_unknown_category(client, admin_user, abstract_lease):
    resp = await client.put(
        f"/api/v1/leases/{abstract_lease.id}/abstract/not_a_category",
        headers=auth_headers(admin_user),
        json={"notes": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upsert_rejects_unknown_field(client, admin_user, abstract_lease):
    resp = await client.put(
        f"/api/v1/leases/{abstract_lease.id}/abstract/security_deposit",
        headers=auth_headers(admin_user),
        json={"content": {"bogus_field": 1}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upsert_rejects_invalid_status(client, admin_user, abstract_lease):
    resp = await client.put(
        f"/api/v1/leases/{abstract_lease.id}/abstract/security_deposit",
        headers=auth_headers(admin_user),
        json={"status": "bogus"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_viewer_cannot_edit_abstract(client, viewer_user, db_session):
    lease = Lease(
        id=uuid.uuid4(),
        organization_id=viewer_user.organization_id,
        lease_name="Viewer Lease",
        expiration_year=2030,
    )
    db_session.add(lease)
    await db_session.commit()

    resp = await client.put(
        f"/api/v1/leases/{lease.id}/abstract/security_deposit",
        headers=auth_headers(viewer_user),
        json={"notes": "x"},
    )
    assert resp.status_code == 403

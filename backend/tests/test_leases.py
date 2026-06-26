import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_create_lease(client, admin_user, sample_office):
    resp = await client.post("/api/v1/leases", headers=auth_headers(admin_user), json={
        "lease_name": "Test Lease",
        "office_id": str(sample_office.id),
        "expiration_year": 2027,
        "lessor_name": "ACME Properties",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["lease_name"] == "Test Lease"
    assert data["expiration_year"] == 2027


@pytest.mark.asyncio
async def test_list_leases(client, admin_user, sample_office):
    # Create two leases
    for i in range(2):
        await client.post("/api/v1/leases", headers=auth_headers(admin_user), json={
            "lease_name": f"Lease {i}",
            "office_id": str(sample_office.id),
            "expiration_year": 2027,
        })

    resp = await client.get("/api/v1/leases", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_delete_lease(client, admin_user, sample_office):
    create_resp = await client.post("/api/v1/leases", headers=auth_headers(admin_user), json={
        "lease_name": "To Delete",
        "office_id": str(sample_office.id),
        "expiration_year": 2026,
    })
    lease_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/leases/{lease_id}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_create_lease_succeeds_when_activity_log_fails(
    client, admin_user, sample_office, monkeypatch
):
    """A failure in best-effort activity logging must not 500 the create.

    Regression: the lease is committed before log_activity runs, so a raised
    error there previously surfaced as "Failed to create lease" even though the
    lease persisted.
    """
    import app.routers.leases as leases_router

    async def boom(*args, **kwargs):
        raise RuntimeError("activity log unavailable")

    monkeypatch.setattr(leases_router, "log_activity", boom)

    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Resilient Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2030,
            "lessor_name": "ACME Properties",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["lease_name"] == "Resilient Lease"

    # And it is actually retrievable.
    listed = await client.get("/api/v1/leases", headers=auth_headers(admin_user))
    assert any(l["lease_name"] == "Resilient Lease" for l in listed.json()["items"])

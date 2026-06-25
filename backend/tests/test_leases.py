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

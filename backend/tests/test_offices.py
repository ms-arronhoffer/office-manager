import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_list_offices_empty(client, admin_user):
    resp = await client.get("/api/v1/offices", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_create_office(client, admin_user):
    resp = await client.post("/api/v1/offices", headers=auth_headers(admin_user), json={
        "office_number": 200,
        "location_type": "office",
        "location_name": "New Office",
        "region_number": 2,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["office_number"] == 200
    assert data["location_name"] == "New Office"


@pytest.mark.asyncio
async def test_get_office(client, admin_user, sample_office):
    resp = await client.get(
        f"/api/v1/offices/{sample_office.id}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["location_name"] == "Test Office"


@pytest.mark.asyncio
async def test_update_office(client, admin_user, sample_office):
    resp = await client.put(
        f"/api/v1/offices/{sample_office.id}",
        headers=auth_headers(admin_user),
        json={"location_name": "Updated Office"},
    )
    assert resp.status_code == 200
    assert resp.json()["location_name"] == "Updated Office"


@pytest.mark.asyncio
async def test_delete_office(client, admin_user, sample_office):
    resp = await client.delete(
        f"/api/v1/offices/{sample_office.id}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_viewer_cannot_create_office(client, viewer_user):
    resp = await client.post("/api/v1/offices", headers=auth_headers(viewer_user), json={
        "office_number": 300,
        "location_type": "office",
        "location_name": "Forbidden Office",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_office_with_owner_fields(client, admin_user):
    """Offices can capture a property owner distinct from the landlord."""
    resp = await client.post("/api/v1/offices", headers=auth_headers(admin_user), json={
        "office_number": 321,
        "location_type": "office",
        "location_name": "Owner Office",
        "owner_same_as_landlord": False,
        "owner_name": "Jane Owner",
        "owner_company": "Owner Holdings LLC",
        "owner_email": "jane@owner.example",
        "owner_phone": "555-1234",
        "owner_address_line_1": "1 Owner Way",
        "owner_city": "Ownerville",
        "owner_state": "CA",
        "owner_zip_code": "90210",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["owner_same_as_landlord"] is False
    assert data["owner_name"] == "Jane Owner"
    assert data["owner_company"] == "Owner Holdings LLC"
    assert data["owner_city"] == "Ownerville"


@pytest.mark.asyncio
async def test_update_office_owner_same_as_landlord(client, admin_user, sample_office):
    resp = await client.put(
        f"/api/v1/offices/{sample_office.id}",
        headers=auth_headers(admin_user),
        json={"owner_same_as_landlord": True, "owner_name": "Acme Landlord"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["owner_same_as_landlord"] is True
    assert data["owner_name"] == "Acme Landlord"

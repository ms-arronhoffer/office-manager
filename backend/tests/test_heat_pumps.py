import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_create_heat_pump_with_data_points(client, admin_user):
    resp = await client.post(
        "/api/v1/hq-hvac/heat-pumps",
        headers=auth_headers(admin_user),
        json={
            "unit_id": "HP-01",
            "location_desc": "Roof - North",
            "make": "Carrier",
            "model": "25HCB6",
            "serial_number": "SN12345",
            "install_year": 2019,
            "refrigerant_type": "R-410A",
            "tonnage": 3.5,
            "seer_rating": 16.0,
            "filter_size": "20x25x1",
            "warranty_expiration": "2029-06-01",
            "last_service_date": "2026-01-15",
            "next_service_date": "2026-07-15",
            "status": "needs_repair",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["refrigerant_type"] == "R-410A"
    assert float(data["tonnage"]) == 3.5
    assert float(data["seer_rating"]) == 16.0
    assert data["filter_size"] == "20x25x1"
    assert data["warranty_expiration"] == "2029-06-01"
    assert data["last_service_date"] == "2026-01-15"
    assert data["next_service_date"] == "2026-07-15"
    assert data["status"] == "needs_repair"


@pytest.mark.asyncio
async def test_create_heat_pump_defaults_status_active(client, admin_user):
    resp = await client.post(
        "/api/v1/hq-hvac/heat-pumps",
        headers=auth_headers(admin_user),
        json={"unit_id": "HP-02"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_update_heat_pump_fields(client, admin_user):
    create = await client.post(
        "/api/v1/hq-hvac/heat-pumps",
        headers=auth_headers(admin_user),
        json={"unit_id": "HP-03", "status": "active"},
    )
    pump_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/hq-hvac/heat-pumps/{pump_id}",
        headers=auth_headers(admin_user),
        json={
            "status": "retired",
            "refrigerant_type": "R-22",
            "next_service_date": "2027-01-01",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "retired"
    assert data["refrigerant_type"] == "R-22"
    assert data["next_service_date"] == "2027-01-01"

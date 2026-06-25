import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_create_landlord_with_data_points(client, admin_user):
    resp = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_user),
        json={
            "contact_name": "Jane Doe",
            "landlord_company": "Acme Holdings LLC",
            "contact_email": "jane@acme.test",
            "contact_phone": "555-1000",
            "secondary_phone": "555-2000",
            "fax": "555-3000",
            "website": "https://acme.test",
            "entity_type": "LLC",
            "tax_id": "12-3456789",
            "management_company": "Acme Management",
            "preferred_payment_method": "ACH",
            "payment_terms": "Net 30",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["entity_type"] == "LLC"
    assert data["tax_id"] == "12-3456789"
    assert data["website"] == "https://acme.test"
    assert data["secondary_phone"] == "555-2000"
    assert data["fax"] == "555-3000"
    assert data["management_company"] == "Acme Management"
    assert data["preferred_payment_method"] == "ACH"
    assert data["payment_terms"] == "Net 30"
    assert data["owned_offices"] == []


@pytest.mark.asyncio
async def test_landlord_owns_multiple_offices(client, admin_user, sample_office, db_session):
    # Create a second office directly so the association can span two offices.
    from app.models.office import Office

    office2 = Office(
        office_number=200,
        location_type="office",
        location_name="Second Office",
        is_active=True,
    )
    db_session.add(office2)
    await db_session.commit()
    await db_session.refresh(office2)
    office2_id = str(office2.id)

    resp = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_user),
        json={
            "contact_name": "Multi Owner",
            "office_ids": [str(sample_office.id), office2_id],
        },
    )
    assert resp.status_code == 201, resp.text
    landlord = resp.json()
    owned_ids = {o["id"] for o in landlord["owned_offices"]}
    assert owned_ids == {str(sample_office.id), office2_id}

    # The office filter returns the landlord for each owned office.
    listing = await client.get(
        f"/api/v1/landlords?office_id={office2_id}",
        headers=auth_headers(admin_user),
    )
    assert listing.status_code == 200
    assert any(l["id"] == landlord["id"] for l in listing.json()["items"])

    # Removing one office via update keeps only the remaining association.
    upd = await client.put(
        f"/api/v1/landlords/{landlord['id']}",
        headers=auth_headers(admin_user),
        json={"office_ids": [str(sample_office.id)]},
    )
    assert upd.status_code == 200, upd.text
    assert {o["id"] for o in upd.json()["owned_offices"]} == {str(sample_office.id)}


@pytest.mark.asyncio
async def test_landlord_contact_typing(client, admin_user):
    created = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_user),
        json={"contact_name": "Primary Owner"},
    )
    landlord_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/landlords/{landlord_id}/contacts",
        headers=auth_headers(admin_user),
        json={
            "contact_name": "Billing Bob",
            "contact_type": "billing",
            "is_primary": True,
            "email": "bob@acme.test",
        },
    )
    assert resp.status_code == 201, resp.text
    contact = resp.json()
    assert contact["contact_type"] == "billing"
    assert contact["is_primary"] is True

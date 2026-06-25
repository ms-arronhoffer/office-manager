import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_management_company_crud_and_landlord_link(client, admin_user):
    # Create a management company with full details.
    resp = await client.post(
        "/api/v1/management-companies",
        headers=auth_headers(admin_user),
        json={
            "name": "Skyline Property Management",
            "contact_name": "Pat Manager",
            "contact_title": "Regional Director",
            "contact_email": "pat@skyline.test",
            "contact_phone": "555-9000",
            "website": "https://skyline.test",
            "portal_url": "https://portal.skyline.test",
            "city": "Austin",
            "state": "TX",
        },
    )
    assert resp.status_code == 201, resp.text
    company = resp.json()
    assert company["name"] == "Skyline Property Management"
    assert company["portal_url"] == "https://portal.skyline.test"
    company_id = company["id"]

    # List shows it.
    listing = await client.get("/api/v1/management-companies", headers=auth_headers(admin_user))
    assert listing.status_code == 200
    assert any(c["id"] == company_id for c in listing.json()["items"])

    # Link a landlord to it and confirm the ref comes back.
    created = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_user),
        json={"contact_name": "Linked Owner", "management_company_id": company_id},
    )
    assert created.status_code == 201, created.text
    landlord = created.json()
    assert landlord["management_company_id"] == company_id
    assert landlord["management_company_ref"]["name"] == "Skyline Property Management"

    # Update the company.
    upd = await client.put(
        f"/api/v1/management-companies/{company_id}",
        headers=auth_headers(admin_user),
        json={"contact_phone": "555-1234"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["contact_phone"] == "555-1234"

    # Soft delete.
    deleted = await client.delete(
        f"/api/v1/management-companies/{company_id}", headers=auth_headers(admin_user)
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_entity_contacts_reusable_across_entities(client, admin_user):
    # Create a management company to attach contacts to.
    company = (
        await client.post(
            "/api/v1/management-companies",
            headers=auth_headers(admin_user),
            json={"name": "Acme PM"},
        )
    ).json()

    # Add an additional contact to the management company.
    resp = await client.post(
        "/api/v1/contacts",
        headers=auth_headers(admin_user),
        json={
            "entity_type": "management_company",
            "entity_id": company["id"],
            "contact_name": "Billing Bob",
            "contact_type": "billing",
            "is_primary": True,
            "email": "bob@acme.test",
            "mobile": "555-7777",
        },
    )
    assert resp.status_code == 201, resp.text
    contact = resp.json()
    assert contact["contact_type"] == "billing"
    assert contact["is_primary"] is True
    assert contact["mobile"] == "555-7777"
    contact_id = contact["id"]

    # List contacts for that entity.
    listing = await client.get(
        f"/api/v1/contacts?entity_type=management_company&entity_id={company['id']}",
        headers=auth_headers(admin_user),
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    # The same endpoint works for a vendor entity type.
    vendor = (
        await client.post(
            "/api/v1/vendors",
            headers=auth_headers(admin_user),
            json={"company_name": "Vendor Co"},
        )
    ).json()
    vresp = await client.post(
        "/api/v1/contacts",
        headers=auth_headers(admin_user),
        json={
            "entity_type": "vendor",
            "entity_id": vendor["id"],
            "contact_name": "Service Sue",
            "contact_type": "maintenance",
        },
    )
    assert vresp.status_code == 201, vresp.text

    # Vendor listing only returns the vendor's contact, not the company's.
    vlist = await client.get(
        f"/api/v1/contacts?entity_type=vendor&entity_id={vendor['id']}",
        headers=auth_headers(admin_user),
    )
    assert len(vlist.json()) == 1
    assert vlist.json()[0]["contact_name"] == "Service Sue"

    # Unsupported entity types are rejected.
    bad = await client.post(
        "/api/v1/contacts",
        headers=auth_headers(admin_user),
        json={"entity_type": "office", "entity_id": vendor["id"], "contact_name": "X"},
    )
    assert bad.status_code == 422

    # Delete a contact.
    deleted = await client.delete(
        f"/api/v1/contacts/{contact_id}", headers=auth_headers(admin_user)
    )
    assert deleted.status_code == 204

import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_client_portal_invite_signup_and_self_service(client, admin_user):
    # Admin creates a landlord to grant portal access to.
    created = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_user),
        json={"contact_name": "Portal Owner", "landlord_company": "Owner LLC"},
    )
    assert created.status_code == 201, created.text
    landlord_id = created.json()["id"]

    # Admin mints a single-use signup invite.
    invite = await client.post(
        "/api/v1/client-portal/invite",
        headers=auth_headers(admin_user),
        json={"entity_type": "landlord", "entity_id": landlord_id},
    )
    assert invite.status_code == 200, invite.text
    signup_token = invite.json()["signup_token"]
    assert signup_token
    assert invite.json()["signup_url"].endswith(signup_token)

    # Redeeming the signup token activates the portal and returns a portal token.
    signup = await client.post("/api/v1/client-portal/signup", json={"token": signup_token})
    assert signup.status_code == 200, signup.text
    portal_token = signup.json()["portal_token"]
    assert signup.json()["entity_type"] == "landlord"

    # The signup token is single-use.
    reused = await client.post("/api/v1/client-portal/signup", json={"token": signup_token})
    assert reused.status_code == 401

    headers = {"X-Portal-Token": portal_token}

    # Read-only profile.
    me = await client.get("/api/v1/client-portal/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["name"] == "Owner LLC"
    assert me.json()["entity_type"] == "landlord"

    # Create a secondary contact; entity scoping is forced server-side.
    new_contact = await client.post(
        "/api/v1/client-portal/contacts",
        headers=headers,
        json={
            "entity_type": "vendor",  # should be ignored/overridden
            "entity_id": "00000000-0000-0000-0000-000000000000",
            "contact_name": "Secondary Sam",
            "email": "sam@owner.test",
        },
    )
    assert new_contact.status_code == 201, new_contact.text
    contact = new_contact.json()
    assert contact["entity_type"] == "landlord"
    assert contact["entity_id"] == landlord_id

    # List contacts shows it.
    listed = await client.get("/api/v1/client-portal/contacts", headers=headers)
    assert listed.status_code == 200
    assert any(c["id"] == contact["id"] for c in listed.json())

    # Update the contact.
    upd = await client.put(
        f"/api/v1/client-portal/contacts/{contact['id']}",
        headers=headers,
        json={"phone": "555-2020"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["phone"] == "555-2020"

    # Upload a document.
    doc = await client.post(
        "/api/v1/client-portal/documents",
        headers=headers,
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    assert doc.status_code == 201, doc.text
    assert doc.json()["original_filename"] == "note.txt"

    docs = await client.get("/api/v1/client-portal/documents", headers=headers)
    assert docs.status_code == 200
    assert len(docs.json()) == 1

    # Delete the contact.
    deleted = await client.delete(
        f"/api/v1/client-portal/contacts/{contact['id']}", headers=headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_client_portal_requires_token(client):
    resp = await client.get("/api/v1/client-portal/me")
    assert resp.status_code == 401

    bad = await client.get("/api/v1/client-portal/me", headers={"X-Portal-Token": "nope"})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_client_portal_invite_rejects_bad_entity_type(client, admin_user):
    resp = await client.post(
        "/api/v1/client-portal/invite",
        headers=auth_headers(admin_user),
        json={"entity_type": "vendor", "entity_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 422

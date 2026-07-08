"""Tests for custom lease templates and enriched residential fields (Residential parity)."""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
TEMPLATES = "/api/v1/lease-templates"
FUNNEL = "/api/v1/leasing-funnel"


async def _make_unit(client, admin_user, sample_office):
    resp = await client.post(
        f"{LEASING}/units",
        json={
            "unit_number": "12B",
            "office_id": str(sample_office.id),
            "address_line_1": "500 Market St",
            "city": "Springfield",
            "state": "IL",
            "zip_code": "62704",
            "property_type": "apartment",
            "amenities": "In-unit laundry",
            "year_built": 1998,
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_rental_unit_enriched_fields_round_trip(client, admin_user, sample_office):
    unit = await _make_unit(client, admin_user, sample_office)
    assert unit["address_line_1"] == "500 Market St"
    assert unit["city"] == "Springfield"
    assert unit["property_type"] == "apartment"
    assert unit["year_built"] == 1998

    patched = await client.patch(
        f"{LEASING}/units/{unit['id']}",
        json={"description": "Corner unit with river views"},
        headers=auth_headers(admin_user),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["description"] == "Corner unit with river views"


async def test_resident_enriched_fields_round_trip(client, admin_user):
    resp = await client.post(
        f"{LEASING}/residents",
        json={
            "first_name": "Dana",
            "last_name": "Rivera",
            "email": "dana@example.com",
            "company": "Acme LLC",
            "alternate_phone": "555-0100",
            "address_line_1": "1 Oak Ave",
            "city": "Metropolis",
            "state": "NY",
            "zip_code": "10001",
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["company"] == "Acme LLC"
    assert body["alternate_phone"] == "555-0100"
    assert body["address_line_1"] == "1 Oak Ave"


async def test_resident_lease_enriched_fields_and_validation(client, admin_user, sample_office):
    unit = await _make_unit(client, admin_user, sample_office)
    resp = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit["id"],
            "lease_type": "fixed_term",
            "rent_amount": "1800.00",
            "late_fee_amount": "75.00",
            "late_fee_grace_days": 5,
            "notice_period_days": 30,
            "pet_deposit": "300.00",
            "renewal_option": True,
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lease_type"] == "fixed_term"
    assert body["late_fee_grace_days"] == 5
    assert body["renewal_option"] is True

    bad = await client.post(
        f"{LEASING}/leases",
        json={"unit_id": unit["id"], "lease_type": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert bad.status_code == 422


async def test_lease_template_crud_and_single_default(client, admin_user):
    created = await client.post(
        TEMPLATES,
        json={
            "name": "Standard 12-month",
            "body": "Lease for {{tenant_name}} at {{property_address}}.",
            "is_default": True,
        },
        headers=auth_headers(admin_user),
    )
    assert created.status_code == 201, created.text
    first_id = created.json()["id"]
    assert created.json()["is_default"] is True

    second = await client.post(
        TEMPLATES,
        json={"name": "Month-to-month", "body": "Body", "is_default": True},
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 201, second.text

    listed = await client.get(TEMPLATES, headers=auth_headers(admin_user))
    assert listed.status_code == 200
    defaults = [t for t in listed.json() if t["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == second.json()["id"]

    deleted = await client.delete(
        f"{TEMPLATES}/{first_id}", headers=auth_headers(admin_user)
    )
    assert deleted.status_code == 204
    remaining = await client.get(TEMPLATES, headers=auth_headers(admin_user))
    assert first_id not in [t["id"] for t in remaining.json()]


async def test_lease_esign_from_template(client, admin_user, sample_office):
    unit = await _make_unit(client, admin_user, sample_office)
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Sam", "last_name": "Tenant", "email": "sam@example.com"},
        headers=auth_headers(admin_user),
    )
    resident_id = resident.json()["id"]
    lease = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit["id"],
            "rent_amount": "2000.00",
            "occupants": [{"resident_id": resident_id, "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    assert lease.status_code == 201, lease.text
    lease_id = lease.json()["id"]

    template = await client.post(
        TEMPLATES,
        json={
            "name": "Residential Lease",
            "body": "This lease at {{property_address}} rents to {{tenant_name}} for {{rent_amount}}.",
        },
        headers=auth_headers(admin_user),
    )
    template_id = template.json()["id"]

    resp = await client.post(
        f"{FUNNEL}/lease-signatures/from-template",
        json={"resident_lease_id": lease_id, "template_id": template_id},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["resident_lease_id"] == lease_id
    assert body["title"] == "Residential Lease"
    # The primary occupant with an email becomes the signing party.
    assert len(body["parties"]) == 1
    assert body["parties"][0]["signer_email"] == "sam@example.com"


async def test_lease_esign_from_template_requires_signer_email(client, admin_user, sample_office):
    unit = await _make_unit(client, admin_user, sample_office)
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "No", "last_name": "Email"},
        headers=auth_headers(admin_user),
    )
    lease = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit["id"],
            "occupants": [{"resident_id": resident.json()["id"], "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    template = await client.post(
        TEMPLATES,
        json={"name": "T", "body": "Body for {{tenant_name}}"},
        headers=auth_headers(admin_user),
    )
    resp = await client.post(
        f"{FUNNEL}/lease-signatures/from-template",
        json={
            "resident_lease_id": lease.json()["id"],
            "template_id": template.json()["id"],
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 409, resp.text


async def test_lease_stores_template_and_custom_fields(client, admin_user, sample_office):
    """A lease can remember its template + custom merge-field values, and the
    e-sign 'from-template' call can reuse the stored template and render the
    custom fields into the signed document."""
    unit = await _make_unit(client, admin_user, sample_office)
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Cara", "last_name": "Custom", "email": "cara@example.com"},
        headers=auth_headers(admin_user),
    )
    resident_id = resident.json()["id"]

    template = await client.post(
        TEMPLATES,
        json={
            "name": "Custom Lease",
            "body": "Tenant {{tenant_name}} parks at {{parking_spot}} for {{rent_amount}}.",
        },
        headers=auth_headers(admin_user),
    )
    template_id = template.json()["id"]

    lease = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit["id"],
            "rent_amount": "2000.00",
            "lease_template_id": template_id,
            "template_field_values": {"parking_spot": "Space 42"},
            "occupants": [{"resident_id": resident_id, "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    assert lease.status_code == 201, lease.text
    lease_body = lease.json()
    lease_id = lease_body["id"]
    assert lease_body["lease_template_id"] == template_id
    assert lease_body["template_field_values"] == {"parking_spot": "Space 42"}

    # Send for e-sign WITHOUT passing a template — it should reuse the lease's.
    resp = await client.post(
        f"{FUNNEL}/lease-signatures/from-template",
        json={"resident_lease_id": lease_id},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    req_id = resp.json()["id"]

    # The rendered/signed body must include the custom field value.
    detail = await client.get(
        f"{FUNNEL}/lease-signatures/{req_id}", headers=auth_headers(admin_user)
    )
    assert detail.status_code == 200

    from sqlalchemy import select
    from app.models.leasing_funnel import LeaseSignatureRequest
    from tests.conftest import _test_session  # type: ignore

    async with _test_session() as session:
        stored = (
            await session.execute(
                select(LeaseSignatureRequest).where(LeaseSignatureRequest.id == req_id)
            )
        ).scalar_one()
        assert "Space 42" in stored.rendered_body


async def test_from_template_without_template_errors(client, admin_user, sample_office):
    """Sending a lease for e-sign with no template passed and none stored fails."""
    unit = await _make_unit(client, admin_user, sample_office)
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "No", "last_name": "Template", "email": "nt@example.com"},
        headers=auth_headers(admin_user),
    )
    lease = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit["id"],
            "occupants": [{"resident_id": resident.json()["id"], "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    resp = await client.post(
        f"{FUNNEL}/lease-signatures/from-template",
        json={"resident_lease_id": lease.json()["id"]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422, resp.text


async def test_sample_lease_template_endpoint(client, admin_user):
    resp = await client.get(f"{TEMPLATES}/sample", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"]
    assert body["description"]
    # The sample must reference merge fields so no lease detail is missed.
    assert "{{tenant_names}}" in body["body"]
    assert "{{rent_amount}}" in body["body"]
    assert "{{property_address}}" in body["body"]

    # It must be usable directly as a new template body.
    created = await client.post(
        TEMPLATES,
        json={"name": body["name"], "description": body["description"], "body": body["body"]},
        headers=auth_headers(admin_user),
    )
    assert created.status_code == 201, created.text

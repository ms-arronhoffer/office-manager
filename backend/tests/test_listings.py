"""Tests for vacancy listings & syndication feeds (Phase 2.5)."""

import xml.etree.ElementTree as ET

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
LISTINGS = "/api/v1/listings"


async def _make_unit(client, admin_user, sample_office, **extra):
    payload = {"unit_number": "10A", "office_id": str(sample_office.id)}
    payload.update(extra)
    resp = await client.post(
        f"{LEASING}/units", json=payload, headers=auth_headers(admin_user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_listing(client, admin_user, unit_id, **extra):
    payload = {"unit_id": unit_id, "title": "Sunny 2BR"}
    payload.update(extra)
    return await client.post(
        f"{LISTINGS}", json=payload, headers=auth_headers(admin_user)
    )


async def test_create_listing_defaults_to_draft(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    resp = await _make_listing(
        client, admin_user, unit_id,
        marketing_rent="2100.00",
        amenities=["dishwasher", "parking"],
        photos=[{"url": "https://cdn.example.com/1.jpg", "caption": "Living room"}],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["published_at"] is None
    assert body["amenities"] == ["dishwasher", "parking"]


async def test_create_listing_rejects_unknown_unit(client, admin_user):
    resp = await _make_listing(
        client, admin_user, "00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_publish_and_unpublish(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(client, admin_user, unit_id)).json()["id"]

    pub = await client.post(
        f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user)
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["published_at"] is not None

    unpub = await client.post(
        f"{LISTINGS}/{listing_id}/unpublish", headers=auth_headers(admin_user)
    )
    assert unpub.status_code == 200
    assert unpub.json()["status"] == "unpublished"


async def test_leased_listing_cannot_be_published(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(client, admin_user, unit_id)).json()["id"]
    await client.post(f"{LISTINGS}/{listing_id}/mark-leased", headers=auth_headers(admin_user))
    resp = await client.post(f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user))
    assert resp.status_code == 409


async def test_update_and_status_filter(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(client, admin_user, unit_id)).json()["id"]
    await client.patch(
        f"{LISTINGS}/{listing_id}",
        json={"headline": "Move-in ready!"},
        headers=auth_headers(admin_user),
    )
    await client.post(f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user))

    published = await client.get(
        f"{LISTINGS}?status=published", headers=auth_headers(admin_user)
    )
    assert published.status_code == 200
    assert len(published.json()) == 1
    assert published.json()[0]["headline"] == "Move-in ready!"

    drafts = await client.get(f"{LISTINGS}?status=draft", headers=auth_headers(admin_user))
    assert drafts.json() == []


async def test_delete_requires_admin(client, admin_user, editor_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(client, admin_user, unit_id)).json()["id"]

    forbidden = await client.delete(
        f"{LISTINGS}/{listing_id}", headers=auth_headers(editor_user)
    )
    assert forbidden.status_code == 403

    ok = await client.delete(
        f"{LISTINGS}/{listing_id}", headers=auth_headers(admin_user)
    )
    assert ok.status_code == 204
    gone = await client.get(f"{LISTINGS}/{listing_id}", headers=auth_headers(admin_user))
    assert gone.status_code == 404


async def _org_for_admin(db_session, admin_user):
    from app.models.organization import Organization

    org = Organization(name="Listing Org", slug=f"listing-org-{admin_user.id.hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    admin_user.organization_id = org.id
    await db_session.commit()
    return org.id


async def test_json_feed_only_published(client, admin_user, sample_office, db_session):
    org_id = await _org_for_admin(db_session, admin_user)
    unit_a = await _make_unit(client, admin_user, sample_office, bedrooms=2, market_rent="1900.00")
    unit_b = await _make_unit(client, admin_user, sample_office, unit_number="10B")

    pub_id = (await _make_listing(
        client, admin_user, unit_a, title="Published one",
    )).json()["id"]
    await client.post(f"{LISTINGS}/{pub_id}/publish", headers=auth_headers(admin_user))
    # A draft listing that must NOT appear in the feed.
    await _make_listing(client, admin_user, unit_b, title="Draft one")

    feed = await client.get(f"{LISTINGS}/feed/{org_id}")
    assert feed.status_code == 200
    data = feed.json()
    assert data["count"] == 1
    listing = data["listings"][0]
    assert listing["title"] == "Published one"
    # bedrooms/rent derived from the unit when the listing omits them.
    assert listing["bedrooms"] == 2
    assert listing["rent"] == "1900.00"


async def test_marketing_rent_overrides_unit_rent(client, admin_user, sample_office, db_session):
    org_id = await _org_for_admin(db_session, admin_user)
    unit_id = await _make_unit(client, admin_user, sample_office, market_rent="1900.00")
    listing_id = (await _make_listing(
        client, admin_user, unit_id, marketing_rent="2250.00",
    )).json()["id"]
    await client.post(f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user))

    feed = await client.get(f"{LISTINGS}/feed/{org_id}")
    assert feed.json()["listings"][0]["rent"] == "2250.00"


async def test_xml_feed(client, admin_user, sample_office, db_session):
    org_id = await _org_for_admin(db_session, admin_user)
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(
        client, admin_user, unit_id, title="XML Home",
        amenities=["pool"],
        photos=[{"url": "https://cdn.example.com/a.jpg"}],
    )).json()["id"]
    await client.post(f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user))

    feed = await client.get(f"{LISTINGS}/feed/{org_id}.xml")
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(feed.content)
    assert root.tag == "Listings"
    listings = root.findall("Listing")
    assert len(listings) == 1
    assert listings[0].find("Title").text == "XML Home"
    assert listings[0].find("Amenities/Amenity").text == "pool"
    assert listings[0].find("Photos/Photo").text == "https://cdn.example.com/a.jpg"


async def test_feed_is_public(client, admin_user, sample_office, db_session):
    org_id = await _org_for_admin(db_session, admin_user)
    # No auth headers → still reachable.
    feed = await client.get(f"{LISTINGS}/feed/{org_id}")
    assert feed.status_code == 200


async def test_listing_reads_require_auth(client):
    resp = await client.get(f"{LISTINGS}")
    assert resp.status_code in (401, 403)

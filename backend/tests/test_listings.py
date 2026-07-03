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


async def _org_for_admin(db_session, admin_user, sample_office=None):
    from app.models.organization import Organization

    org = Organization(name="Listing Org", slug=f"listing-org-{admin_user.id.hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    admin_user.organization_id = org.id
    # Keep the office in the same organization as the admin so unit creation,
    # which validates office_id against the caller's org, still succeeds.
    if sample_office is not None:
        sample_office.organization_id = org.id
    await db_session.commit()
    return org.id


async def test_json_feed_only_published(client, admin_user, sample_office, db_session):
    org_id = await _org_for_admin(db_session, admin_user, sample_office)
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
    org_id = await _org_for_admin(db_session, admin_user, sample_office)
    unit_id = await _make_unit(client, admin_user, sample_office, market_rent="1900.00")
    listing_id = (await _make_listing(
        client, admin_user, unit_id, marketing_rent="2250.00",
    )).json()["id"]
    await client.post(f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user))

    feed = await client.get(f"{LISTINGS}/feed/{org_id}")
    assert feed.json()["listings"][0]["rent"] == "2250.00"


async def test_xml_feed(client, admin_user, sample_office, db_session):
    org_id = await _org_for_admin(db_session, admin_user, sample_office)
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
    org_id = await _org_for_admin(db_session, admin_user, sample_office)
    # No auth headers → still reachable.
    feed = await client.get(f"{LISTINGS}/feed/{org_id}")
    assert feed.status_code == 200


async def test_listing_reads_require_auth(client):
    resp = await client.get(f"{LISTINGS}")
    assert resp.status_code in (401, 403)


# ─── Portal syndication ───────────────────────────────────────────────────────

async def _make_portal(client, admin_user, **extra):
    payload = {"name": "Zillow", "slug": "zillow", "delivery_mode": "feed"}
    payload.update(extra)
    return await client.post(
        f"{LISTINGS}/portals", json=payload, headers=auth_headers(admin_user)
    )


async def test_portal_catalog_lists_known_networks(client, admin_user):
    resp = await client.get(f"{LISTINGS}/portals/catalog", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    slugs = {p["slug"] for p in resp.json()}
    assert {"zillow", "homes", "apartments"} <= slugs


async def test_portal_crud(client, admin_user):
    created = await _make_portal(client, admin_user)
    assert created.status_code == 201, created.text
    portal_id = created.json()["id"]

    listed = await client.get(f"{LISTINGS}/portals", headers=auth_headers(admin_user))
    assert any(p["id"] == portal_id for p in listed.json())

    patched = await client.patch(
        f"{LISTINGS}/portals/{portal_id}",
        json={"is_enabled": False},
        headers=auth_headers(admin_user),
    )
    assert patched.status_code == 200
    assert patched.json()["is_enabled"] is False

    deleted = await client.delete(
        f"{LISTINGS}/portals/{portal_id}", headers=auth_headers(admin_user)
    )
    assert deleted.status_code == 204


async def test_webhook_portal_requires_endpoint(client, admin_user):
    resp = await _make_portal(
        client, admin_user, name="Custom", slug="custom", delivery_mode="webhook"
    )
    assert resp.status_code == 400


async def test_syndicate_published_listing(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(client, admin_user, unit_id)).json()["id"]
    await client.post(f"{LISTINGS}/{listing_id}/publish", headers=auth_headers(admin_user))
    portal_id = (await _make_portal(client, admin_user)).json()["id"]

    resp = await client.post(
        f"{LISTINGS}/{listing_id}/syndicate",
        json={"portal_ids": [portal_id]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200, resp.text
    records = resp.json()
    assert len(records) == 1
    assert records[0]["portal_id"] == portal_id
    assert records[0]["status"] == "posted"

    # Idempotent re-syndication refreshes the same record.
    again = await client.post(
        f"{LISTINGS}/{listing_id}/syndicate",
        json={"portal_ids": [portal_id]},
        headers=auth_headers(admin_user),
    )
    assert again.status_code == 200
    assert len(again.json()) == 1

    status_resp = await client.get(
        f"{LISTINGS}/{listing_id}/syndications", headers=auth_headers(admin_user)
    )
    assert status_resp.status_code == 200
    assert len(status_resp.json()) == 1


async def test_cannot_syndicate_unpublished_listing(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    listing_id = (await _make_listing(client, admin_user, unit_id)).json()["id"]
    portal_id = (await _make_portal(client, admin_user)).json()["id"]

    resp = await client.post(
        f"{LISTINGS}/{listing_id}/syndicate",
        json={"portal_ids": [portal_id]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 409

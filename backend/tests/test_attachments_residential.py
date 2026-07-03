"""Tests for resident & rental-unit document uploads (attachments)."""

import io

import pytest

from app.config import settings
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
API = "/api/v1"


@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))


def _file(name="id.txt"):
    return (name, io.BytesIO(b"resident identity document"), "text/plain")


async def _make_unit(client, admin_user, sample_office):
    resp = await client.post(
        f"{LEASING}/units",
        json={"unit_number": "7C", "office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_resident(client, admin_user):
    resp = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Sam", "last_name": "Lee", "email": "sam@example.com"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_limits_expose_new_entity_types(client, admin_user):
    resp = await client.get(f"{API}/attachments/limits", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    types = resp.json()["allowed_entity_types"]
    assert "resident" in types
    assert "rental_unit" in types


async def test_upload_and_download_resident_document(client, admin_user):
    resident_id = await _make_resident(client, admin_user)
    up = await client.post(
        f"{API}/resident/{resident_id}/attachments",
        files={"file": _file()},
        data={"description": "Driver's license"},
        headers=auth_headers(admin_user),
    )
    assert up.status_code == 201, up.text
    attachment_id = up.json()["id"]

    listed = await client.get(
        f"{API}/resident/{resident_id}/attachments", headers=auth_headers(admin_user)
    )
    assert listed.status_code == 200
    assert any(a["id"] == attachment_id for a in listed.json())

    dl = await client.get(
        f"{API}/attachments/{attachment_id}/download", headers=auth_headers(admin_user)
    )
    assert dl.status_code == 200
    assert dl.content == b"resident identity document"


async def test_upload_rental_unit_document(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    up = await client.post(
        f"{API}/rental_unit/{unit_id}/attachments",
        files={"file": _file("inspection.txt")},
        headers=auth_headers(admin_user),
    )
    assert up.status_code == 201, up.text

    counts = await client.get(
        f"{API}/attachments/counts",
        params={"entity_type": "rental_unit", "ids": unit_id},
        headers=auth_headers(admin_user),
    )
    assert counts.status_code == 200
    assert counts.json()[unit_id] == 1


async def test_upload_rejects_unknown_parent(client, admin_user):
    resp = await client.post(
        f"{API}/resident/00000000-0000-0000-0000-000000000000/attachments",
        files={"file": _file()},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 404

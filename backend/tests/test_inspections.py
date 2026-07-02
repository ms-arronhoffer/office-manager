"""Tests for the Property Inspections module (Phase 1.5)."""

import uuid

import pytest

from app.models.inspection import Inspection, InspectionItemResult
from app.services import inspection_service as svc
from tests.conftest import auth_headers


# ─── Service unit tests ──────────────────────────────────────────────────────

def _inspection(results):
    ins = Inspection(id=uuid.uuid4(), office_id=uuid.uuid4(), title="T")
    ins.results = [
        InspectionItemResult(
            label=f"item{i}", sort_order=i, is_required=req, result=res
        )
        for i, (req, res) in enumerate(results)
    ]
    return ins


def test_compute_overall_fail_when_required_fails():
    ins = _inspection([(True, "pass"), (True, "fail")])
    assert svc.compute_overall_result(ins) == "fail"


def test_compute_overall_pass_when_all_required_pass():
    ins = _inspection([(True, "pass"), (False, "na")])
    assert svc.compute_overall_result(ins) == "pass"


def test_compute_overall_na_when_nothing_passed():
    ins = _inspection([(True, "na"), (False, "na")])
    assert svc.compute_overall_result(ins) == "na"


def test_non_required_fail_does_not_fail_overall():
    ins = _inspection([(True, "pass"), (False, "fail")])
    assert svc.compute_overall_result(ins) == "pass"


def test_required_items_scored():
    assert svc.required_items_scored(_inspection([(True, "pass"), (False, None)])) is True
    assert svc.required_items_scored(_inspection([(True, None)])) is False


def test_validate_result():
    assert svc.validate_result(None) is None
    assert svc.validate_result("pass") == "pass"
    with pytest.raises(svc.InspectionError):
        svc.validate_result("maybe")


# ─── API tests ───────────────────────────────────────────────────────────────

async def _make_template(client, headers):
    return await client.post(
        "/api/v1/inspections/templates",
        headers=headers,
        json={
            "name": "Quarterly HVAC",
            "category": "hvac",
            "items": [
                {"label": "Filters clean", "is_required": True},
                {"label": "No leaks", "is_required": True},
                {"label": "Optional cosmetic", "is_required": False},
            ],
        },
    )


@pytest.mark.asyncio
async def test_viewer_cannot_create_template(client, viewer_user):
    resp = await client.post(
        "/api/v1/inspections/templates",
        headers=auth_headers(viewer_user),
        json={"name": "X", "items": []},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_read_templates(client, viewer_user):
    resp = await client.get("/api/v1/inspections/templates", headers=auth_headers(viewer_user))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_template_crud(client, editor_user):
    headers = auth_headers(editor_user)
    created = await _make_template(client, headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert len(body["items"]) == 3

    patched = await client.patch(
        f"/api/v1/inspections/templates/{body['id']}",
        headers=headers,
        json={"name": "Renamed"},
    )
    assert patched.json()["name"] == "Renamed"

    deleted = await client.delete(
        f"/api/v1/inspections/templates/{body['id']}", headers=headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_create_inspection_snapshots_items(client, editor_user, sample_office):
    headers = auth_headers(editor_user)
    template = (await _make_template(client, headers)).json()
    resp = await client.post(
        "/api/v1/inspections",
        headers=headers,
        json={
            "office_id": str(sample_office.id),
            "title": "Q1 inspection",
            "template_id": template["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "scheduled"
    assert len(body["results"]) == 3
    assert all(r["result"] is None for r in body["results"])


@pytest.mark.asyncio
async def test_inspection_unknown_office(client, editor_user):
    headers = auth_headers(editor_user)
    resp = await client.post(
        "/api/v1/inspections",
        headers=headers,
        json={"office_id": str(uuid.uuid4()), "title": "X"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_record_results_and_complete_pass(client, editor_user, sample_office):
    headers = auth_headers(editor_user)
    template = (await _make_template(client, headers)).json()
    inspection = (
        await client.post(
            "/api/v1/inspections",
            headers=headers,
            json={
                "office_id": str(sample_office.id),
                "title": "Q1",
                "template_id": template["id"],
            },
        )
    ).json()

    # Score all required items as pass; optional left unset.
    updates = [
        {"id": r["id"], "result": "pass"}
        for r in inspection["results"]
        if r["is_required"]
    ]
    patched = await client.patch(
        f"/api/v1/inspections/{inspection['id']}",
        headers=headers,
        json={"results": updates},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "in_progress"

    completed = await client.post(
        f"/api/v1/inspections/{inspection['id']}/complete", headers=headers
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["overall_result"] == "pass"


@pytest.mark.asyncio
async def test_complete_requires_all_required_scored(client, editor_user, sample_office):
    headers = auth_headers(editor_user)
    template = (await _make_template(client, headers)).json()
    inspection = (
        await client.post(
            "/api/v1/inspections",
            headers=headers,
            json={
                "office_id": str(sample_office.id),
                "title": "Q1",
                "template_id": template["id"],
            },
        )
    ).json()
    resp = await client.post(
        f"/api/v1/inspections/{inspection['id']}/complete", headers=headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_completed_inspection_is_locked(client, editor_user, sample_office):
    headers = auth_headers(editor_user)
    template = (await _make_template(client, headers)).json()
    inspection = (
        await client.post(
            "/api/v1/inspections",
            headers=headers,
            json={
                "office_id": str(sample_office.id),
                "title": "Q1",
                "template_id": template["id"],
            },
        )
    ).json()
    fail_updates = [
        {"id": r["id"], "result": "fail" if i == 0 else "pass"}
        for i, r in enumerate(r2 for r2 in inspection["results"] if r2["is_required"])
    ]
    await client.patch(
        f"/api/v1/inspections/{inspection['id']}",
        headers=headers,
        json={"results": fail_updates},
    )
    completed = await client.post(
        f"/api/v1/inspections/{inspection['id']}/complete", headers=headers
    )
    assert completed.json()["overall_result"] == "fail"

    # Further edits rejected.
    resp = await client.patch(
        f"/api/v1/inspections/{inspection['id']}",
        headers=headers,
        json={"title": "nope"},
    )
    assert resp.status_code == 409

"""Tests for the Digital Waivers API (Pro+).

Covers entitlement gating, template CRUD, the visitor send + public token
signing flow, e-signature audit capture, and locked-after-signing behavior.
"""
import pytest

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User


async def _make_org_user(db_session, plan: str, email: str) -> dict[str, str]:
    org = Organization(name=f"Org {plan}", slug=f"org-w-{email[:5]}", plan=plan)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": "Bearer " + token}


async def _create_template(client, headers) -> str:
    resp = await client.post(
        "/api/v1/waivers/templates",
        headers=headers,
        json={
            "name": "Visitor Waiver",
            "body": "Hello {{recipient_name}}, you agree to the terms with {{organization_name}}.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_templates_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "starter@w.com")
    resp = await client.get("/api/v1/waivers/templates", headers=headers)
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_template_crud_pro(client, db_session):
    headers = await _make_org_user(db_session, "pro", "pro@w.com")
    template_id = await _create_template(client, headers)

    listed = await client.get("/api/v1/waivers/templates", headers=headers)
    assert listed.status_code == 200
    assert any(t["id"] == template_id for t in listed.json())

    updated = await client.put(
        f"/api/v1/waivers/templates/{template_id}",
        headers=headers,
        json={"name": "Renamed Waiver"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed Waiver"

    deleted = await client.delete(f"/api/v1/waivers/templates/{template_id}", headers=headers)
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_visitor_send_and_public_sign_flow(client, db_session, monkeypatch):
    # Email is best-effort; ensure no real send is attempted.
    import app.routers.waivers as waivers_router

    async def fake_send_email(*a, **k):
        return None

    monkeypatch.setattr(waivers_router, "send_email", fake_send_email)

    headers = await _make_org_user(db_session, "pro", "pro2@w.com")
    template_id = await _create_template(client, headers)

    send = await client.post(
        "/api/v1/waivers/send",
        headers=headers,
        json={
            "template_id": template_id,
            "recipient_type": "visitor",
            "recipient_email": "visitor@example.com",
            "recipient_name": "Pat Visitor",
        },
    )
    assert send.status_code == 201, send.text
    request_id = send.json()["id"]
    assert send.json()["status"] == "sent"

    # Recover the signing token from the DB (not exposed in the API response body).
    from sqlalchemy import select
    from app.models.waiver import WaiverRequest

    row = (
        await db_session.execute(select(WaiverRequest).where(WaiverRequest.id == request_id))
    ).scalar_one()
    token = row.sign_token

    # Public view (no auth)
    view = await client.get(f"/api/v1/waivers/sign/{token}")
    assert view.status_code == 200, view.text
    assert "Pat Visitor" in view.json()["body"]
    assert view.json()["consent_text"]

    # Sign (no auth) with visitor details
    sign = await client.post(
        f"/api/v1/waivers/sign/{token}",
        json={
            "signer_name": "Pat Visitor",
            "signer_email": "visitor@example.com",
            "signature_type": "typed",
            "signature_data": "Pat Visitor",
            "consent_agreed": True,
            "visitor_details": [{"label": "Company", "value": "Acme"}],
        },
    )
    assert sign.status_code == 200, sign.text
    assert sign.json()["status"] == "signed"

    # Audit fields captured
    from app.models.waiver import WaiverSignature

    sig = (
        await db_session.execute(
            select(WaiverSignature).where(WaiverSignature.request_id == request_id)
        )
    ).scalar_one()
    assert sig.consent_agreed is True
    assert sig.signed_at is not None
    assert sig.document_hash == row.document_hash
    assert sig.consent_text

    # Locked after signing — re-signing is rejected
    resign = await client.post(
        f"/api/v1/waivers/sign/{token}",
        json={
            "signer_name": "Pat Visitor",
            "signature_type": "typed",
            "signature_data": "Pat Visitor",
            "consent_agreed": True,
        },
    )
    assert resign.status_code == 409, resign.text


@pytest.mark.asyncio
async def test_sign_requires_consent(client, db_session, monkeypatch):
    import app.routers.waivers as waivers_router

    async def fake_send_email(*a, **k):
        return None

    monkeypatch.setattr(waivers_router, "send_email", fake_send_email)

    headers = await _make_org_user(db_session, "pro", "pro3@w.com")
    template_id = await _create_template(client, headers)
    send = await client.post(
        "/api/v1/waivers/send",
        headers=headers,
        json={
            "template_id": template_id,
            "recipient_type": "visitor",
            "recipient_email": "v2@example.com",
            "recipient_name": "No Consent",
        },
    )
    request_id = send.json()["id"]
    from sqlalchemy import select
    from app.models.waiver import WaiverRequest

    token = (
        await db_session.execute(select(WaiverRequest).where(WaiverRequest.id == request_id))
    ).scalar_one().sign_token

    resp = await client.post(
        f"/api/v1/waivers/sign/{token}",
        json={
            "signer_name": "No Consent",
            "signature_type": "typed",
            "signature_data": "x",
            "consent_agreed": False,
        },
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_duplicate_pending_blocks_resend_and_force_overrides(client, db_session, monkeypatch):
    import app.routers.waivers as waivers_router

    async def fake_send_email(*a, **k):
        return None

    monkeypatch.setattr(waivers_router, "send_email", fake_send_email)

    headers = await _make_org_user(db_session, "pro", "dup@w.com")
    template_id = await _create_template(client, headers)

    body = {
        "template_id": template_id,
        "recipient_type": "visitor",
        "recipient_email": "Dup.Person@Example.com",  # mixed-case on purpose
        "recipient_name": "Dup Person",
    }
    first = await client.post("/api/v1/waivers/send", headers=headers, json=body)
    assert first.status_code == 201, first.text
    # Email is normalized on persist.
    assert first.json()["recipient_email"] == "dup.person@example.com"

    # A second send to the same (template, email) is blocked while the first is pending,
    # and the comparison is case-insensitive.
    dup = await client.post(
        "/api/v1/waivers/send",
        headers=headers,
        json={**body, "recipient_email": "dup.person@example.com"},
    )
    assert dup.status_code == 409, dup.text
    assert dup.json()["detail"]["existing_request_id"] == first.json()["id"]

    # force=true overrides.
    forced = await client.post(
        "/api/v1/waivers/send", headers=headers, json={**body, "force": True}
    )
    assert forced.status_code == 201, forced.text


@pytest.mark.asyncio
async def test_duplicate_check_endpoint(client, db_session, monkeypatch):
    import app.routers.waivers as waivers_router

    async def fake_send_email(*a, **k):
        return None

    monkeypatch.setattr(waivers_router, "send_email", fake_send_email)

    headers = await _make_org_user(db_session, "pro", "dchk@w.com")
    template_id = await _create_template(client, headers)

    # No waiver yet → no pending.
    pre = await client.post(
        "/api/v1/waivers/recipients/duplicate-check",
        headers=headers,
        json={"recipient_email": "check@example.com", "template_id": template_id},
    )
    assert pre.status_code == 200, pre.text
    assert pre.json()["has_pending"] is False

    await client.post(
        "/api/v1/waivers/send",
        headers=headers,
        json={
            "template_id": template_id,
            "recipient_type": "visitor",
            "recipient_email": "check@example.com",
            "recipient_name": "Check Person",
        },
    )

    post = await client.post(
        "/api/v1/waivers/recipients/duplicate-check",
        headers=headers,
        json={"recipient_email": "CHECK@example.com"},
    )
    assert post.status_code == 200, post.text
    assert post.json()["has_pending"] is True
    assert len(post.json()["history"]) == 1


@pytest.mark.asyncio
async def test_recipient_search(client, db_session, monkeypatch):
    import app.routers.waivers as waivers_router

    async def fake_send_email(*a, **k):
        return None

    monkeypatch.setattr(waivers_router, "send_email", fake_send_email)

    headers = await _make_org_user(db_session, "pro", "rsearch@w.com")
    template_id = await _create_template(client, headers)

    await client.post(
        "/api/v1/waivers/send",
        headers=headers,
        json={
            "template_id": template_id,
            "recipient_type": "visitor",
            "recipient_email": "marie.curie@example.com",
            "recipient_name": "Marie Curie",
        },
    )

    res = await client.get("/api/v1/waivers/recipients/search?q=marie", headers=headers)
    assert res.status_code == 200, res.text
    emails = [r["email"] for r in res.json()]
    assert "marie.curie@example.com" in emails

"""Tests for the leasing funnel (Phase 2.4)."""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
FUNNEL = "/api/v1/leasing-funnel"


async def _party_tokens(db_session, req_id):
    from app.models.leasing_funnel import LeaseSignatureParty
    from sqlalchemy import select

    parties = (
        await db_session.execute(
            select(LeaseSignatureParty)
            .where(LeaseSignatureParty.request_id == req_id)
            .order_by(LeaseSignatureParty.sign_order)
        )
    ).scalars().all()
    return [p.sign_token for p in parties]


async def _make_unit(client, admin_user, sample_office):
    unit = await client.post(
        f"{LEASING}/units",
        json={"unit_number": "3C", "office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    return unit.json()["id"]


async def test_public_application_submission(client, admin_user, sample_office, db_session):
    from app.models.organization import Organization

    org = Organization(name="Public Org", slug="public-org")
    db_session.add(org)
    await db_session.commit()
    resp = await client.post(
        f"{FUNNEL}/applications/public",
        json={
            "organization_id": str(org.id),
            "applicant_first_name": "Pat",
            "applicant_last_name": "Prospect",
            "applicant_email": "pat@example.com",
            "monthly_income": "6000.00",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "submitted"
    assert resp.json()["applicant_email"] == "pat@example.com"


async def test_public_application_bad_org(client):
    resp = await client.post(
        f"{FUNNEL}/applications/public",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000000",
            "applicant_first_name": "X",
            "applicant_last_name": "Y",
            "applicant_email": "x@y.com",
        },
    )
    assert resp.status_code == 404


async def test_screening_stub_and_status_progression(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    app = await client.post(
        f"{FUNNEL}/applications",
        json={
            "unit_id": unit_id,
            "applicant_first_name": "Sam",
            "applicant_last_name": "Screen",
            "applicant_email": "sam@example.com",
        },
        headers=auth_headers(admin_user),
    )
    app_id = app.json()["id"]
    screen = await client.post(
        f"{FUNNEL}/applications/{app_id}/screen", headers=auth_headers(admin_user)
    )
    assert screen.status_code == 200, screen.text
    # Unconfigured provider → manual review recommendation.
    assert screen.json()["provider"] == "manual"
    assert screen.json()["recommendation"] == "review"

    # Application advanced to screening.
    got = await client.get(f"{FUNNEL}/applications/{app_id}", headers=auth_headers(admin_user))
    assert got.json()["status"] == "screening"


async def test_application_decision_and_convert(client, admin_user, sample_office):
    unit_id = await _make_unit(client, admin_user, sample_office)
    app = await client.post(
        f"{FUNNEL}/applications",
        json={
            "unit_id": unit_id,
            "applicant_first_name": "Ada",
            "applicant_last_name": "Approve",
            "applicant_email": "ada@example.com",
        },
        headers=auth_headers(admin_user),
    )
    app_id = app.json()["id"]

    approve = await client.patch(
        f"{FUNNEL}/applications/{app_id}",
        json={"status": "approved", "decision_notes": "Great applicant"},
        headers=auth_headers(admin_user),
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    conv = await client.post(
        f"{FUNNEL}/applications/{app_id}/convert", headers=auth_headers(admin_user)
    )
    assert conv.status_code == 200, conv.text
    assert conv.json()["status"] == "converted"
    assert conv.json()["resident_id"] is not None

    # The resident now exists in the leasing domain.
    residents = await client.get(f"{LEASING}/residents", headers=auth_headers(admin_user))
    names = [r["last_name"] for r in residents.json()]
    assert "Approve" in names


async def test_invalid_status_transition_rejected(client, admin_user):
    app = await client.post(
        f"{FUNNEL}/applications",
        json={
            "applicant_first_name": "Deb",
            "applicant_last_name": "Deny",
            "applicant_email": "deb@example.com",
        },
        headers=auth_headers(admin_user),
    )
    app_id = app.json()["id"]
    # Deny, then attempt to approve (terminal state).
    await client.patch(
        f"{FUNNEL}/applications/{app_id}", json={"status": "denied"},
        headers=auth_headers(admin_user),
    )
    bad = await client.patch(
        f"{FUNNEL}/applications/{app_id}", json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    assert bad.status_code == 409


async def test_convert_requires_approval(client, admin_user):
    app = await client.post(
        f"{FUNNEL}/applications",
        json={
            "applicant_first_name": "Not",
            "applicant_last_name": "Approved",
            "applicant_email": "na@example.com",
        },
        headers=auth_headers(admin_user),
    )
    app_id = app.json()["id"]
    resp = await client.post(
        f"{FUNNEL}/applications/{app_id}/convert", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 409


# ─── Lease e-signing ──────────────────────────────────────────────────────────

async def _create_envelope(client, admin_user, parties):
    return await client.post(
        f"{FUNNEL}/lease-signatures",
        json={
            "title": "Residential Lease Agreement",
            "body": "This lease is between {{organization_name}} and the tenant. Dated {{date}}.",
            "parties": parties,
        },
        headers=auth_headers(admin_user),
    )


async def test_lease_esign_full_multiparty_flow(client, admin_user, db_session):
    created = await _create_envelope(
        client, admin_user,
        [
            {"signer_name": "Tim Tenant", "signer_email": "tim@example.com", "role": "tenant"},
            {"signer_name": "Larry Landlord", "signer_email": "larry@example.com", "role": "landlord"},
        ],
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "sent"
    assert len(body["parties"]) == 2
    req_id = body["id"]

    tokens = await _party_tokens(db_session, req_id)
    assert len(tokens) == 2

    # First party signs → partially_signed.
    first = await client.post(
        f"{FUNNEL}/lease-sign/{tokens[0]}",
        json={"signature_type": "typed", "signature_data": "Tim Tenant", "consent_agreed": True},
    )
    assert first.status_code == 200, first.text
    assert first.json()["request_status"] == "partially_signed"
    assert first.json()["party_status"] == "signed"

    # Second party signs → completed.
    second = await client.post(
        f"{FUNNEL}/lease-sign/{tokens[1]}",
        json={"signature_type": "typed", "signature_data": "Larry Landlord", "consent_agreed": True},
    )
    assert second.status_code == 200, second.text
    assert second.json()["request_status"] == "completed"

    # Completed lease PDF downloads.
    pdf = await client.get(
        f"{FUNNEL}/lease-signatures/{req_id}/pdf", headers=auth_headers(admin_user)
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"


async def test_lease_esign_requires_consent(client, admin_user, db_session):
    created = await _create_envelope(
        client, admin_user,
        [{"signer_name": "No Consent", "signer_email": "nc@example.com"}],
    )
    req_id = created.json()["id"]
    token = (await _party_tokens(db_session, req_id))[0]

    resp = await client.post(
        f"{FUNNEL}/lease-sign/{token}",
        json={"signature_type": "typed", "signature_data": "x", "consent_agreed": False},
    )
    assert resp.status_code == 409


async def test_lease_esign_public_view_marks_viewed(client, admin_user, db_session):
    created = await _create_envelope(
        client, admin_user,
        [{"signer_name": "Vi Viewer", "signer_email": "vi@example.com"}],
    )
    req_id = created.json()["id"]
    token = (await _party_tokens(db_session, req_id))[0]

    view = await client.get(f"{FUNNEL}/lease-sign/{token}")
    assert view.status_code == 200
    assert view.json()["party_status"] == "viewed"
    # Rendered body has merge fields substituted.
    assert "{{organization_name}}" not in view.json()["body"]


async def test_lease_esign_decline_voids_envelope(client, admin_user, db_session):
    created = await _create_envelope(
        client, admin_user,
        [
            {"signer_name": "A", "signer_email": "a@example.com"},
            {"signer_name": "B", "signer_email": "b@example.com"},
        ],
    )
    req_id = created.json()["id"]
    token = (await _party_tokens(db_session, req_id))[0]

    decline = await client.post(f"{FUNNEL}/lease-sign/{token}/decline")
    assert decline.status_code == 200
    assert decline.json()["request_status"] == "declined"

    detail = await client.get(
        f"{FUNNEL}/lease-signatures/{req_id}", headers=auth_headers(admin_user)
    )
    assert detail.json()["status"] == "declined"


async def test_lease_esign_bad_role_rejected(client, admin_user):
    resp = await _create_envelope(
        client, admin_user,
        [{"signer_name": "X", "signer_email": "x@example.com", "role": "bogus"}],
    )
    assert resp.status_code == 422


async def test_funnel_reads_require_auth(client):
    resp = await client.get(f"{FUNNEL}/applications")
    assert resp.status_code in (401, 403)


async def test_lease_esign_emails_each_party(client, admin_user, db_session):
    """Sending a lease for e-sign queues a signing email per party (EmailLog)."""
    from sqlalchemy import select
    from app.models.email import EmailLog

    before = (
        await db_session.execute(select(EmailLog).where(EmailLog.subject.like("Signature requested:%")))
    ).scalars().all()
    before_ids = {e.id for e in before}

    created = await _create_envelope(
        client, admin_user,
        [
            {"signer_name": "Pat Party", "signer_email": "pat@example.com", "role": "tenant"},
            {"signer_name": "Sam Signer", "signer_email": "sam@example.com", "role": "cosigner"},
        ],
    )
    assert created.status_code == 201, created.text

    logs = (
        await db_session.execute(select(EmailLog).where(EmailLog.subject.like("Signature requested:%")))
    ).scalars().all()
    new_logs = [e for e in logs if e.id not in before_ids]
    recipients = {e.sent_to for e in new_logs}
    assert "pat@example.com" in recipients
    assert "sam@example.com" in recipients

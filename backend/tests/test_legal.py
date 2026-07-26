"""Tests for the public legal-document API and signup legal acceptance."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.services import legal_service

from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_list_legal_documents(client: AsyncClient):
    resp = await client.get("/api/v1/legal")
    assert resp.status_code == 200
    docs = resp.json()
    slugs = {d["slug"] for d in docs}
    assert {"terms-of-service", "eula", "privacy-policy", "acceptable-use-policy"} <= slugs
    for doc in docs:
        assert doc["title"]
        assert doc["version"]
        assert "required_at_signup" in doc


@pytest.mark.asyncio
async def test_get_legal_document_renders_html(client: AsyncClient):
    resp = await client.get("/api/v1/legal/terms-of-service")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "terms-of-service"
    assert "<h1>" in body["html"]
    assert body["markdown"].startswith("# Terms of Service")


@pytest.mark.asyncio
async def test_get_unknown_legal_document_404(client: AsyncClient):
    resp = await client.get("/api/v1/legal/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_signup_requires_legal_acceptance(client: AsyncClient):
    resp = await client.post(
        "/api/v1/organizations/signup",
        json={
            "org_name": "No Consent Co",
            "email": "noconsent@example.com",
            "password": "SuperSecret123!",
            "display_name": "No Consent",
            "accepted_legal": False,
        },
    )
    # Pydantic validation rejects accepted_legal=False before org creation.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_signup_records_legal_acceptance(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post(
        "/api/v1/organizations/signup",
        json={
            "org_name": "Consent Co",
            "email": "consent@example.com",
            "password": "SuperSecret123!",
            "display_name": "Consent Admin",
            "accepted_legal": True,
        },
    )
    assert resp.status_code == 201, resp.text

    org = (
        await db_session.execute(
            select(Organization).where(Organization.slug == "consent-co")
        )
    ).scalar_one()
    assert org.legal_accepted_at is not None
    assert org.legal_accepted_versions == legal_service.current_versions()


@pytest.mark.asyncio
async def test_signup_records_user_legal_acceptance(
    client: AsyncClient, db_session: AsyncSession
):
    """The org creator's signup agreement is their per-user acceptance record."""
    from app.models.user import User

    resp = await client.post(
        "/api/v1/organizations/signup",
        json={
            "org_name": "Founder Co",
            "email": "founder@example.com",
            "password": "SuperSecret123!",
            "display_name": "Founder Admin",
            "accepted_legal": True,
        },
    )
    assert resp.status_code == 201, resp.text

    user = (
        await db_session.execute(
            select(User).where(User.email == "founder@example.com")
        )
    ).scalar_one()
    assert user.legal_accepted_at is not None
    assert user.legal_accepted_versions == legal_service.current_versions()

    me = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["legal_accepted_at"] is not None
    # The founder already agreed at signup and is not re-prompted.
    assert body["legal_acceptance_required"] is False


@pytest.mark.asyncio
async def test_new_user_requires_and_can_accept_legal(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """A user who has not accepted the legal documents must accept before their
    account is treated as active; acceptance is recorded for auditing."""
    from app.models.user import User

    headers = auth_headers(admin_user)

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["legal_accepted_at"] is None
    assert me.json()["legal_acceptance_required"] is True

    # Cannot record acceptance without actually agreeing.
    bad = await client.post(
        "/api/v1/auth/me/accept-legal",
        headers=headers,
        json={"accepted_legal": False},
    )
    assert bad.status_code == 422

    ok = await client.post(
        "/api/v1/auth/me/accept-legal",
        headers=headers,
        json={"accepted_legal": True},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["legal_accepted_at"] is not None
    assert body["legal_acceptance_required"] is False

    # Acceptance is persisted for auditing.
    refreshed = (
        await db_session.execute(select(User).where(User.id == admin_user.id))
    ).scalar_one()
    assert refreshed.legal_accepted_at is not None
    assert refreshed.legal_accepted_versions == legal_service.current_versions()

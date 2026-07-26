"""Tests for the public legal-document API and signup legal acceptance."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.services import legal_service


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

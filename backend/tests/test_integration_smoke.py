"""Opt-in, non-mutating smoke checks for dedicated provider sandboxes."""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


def _required(*names: str) -> list[str]:
    values = [os.getenv(name, "").strip() for name in names]
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        pytest.skip(f"sandbox credentials absent: {', '.join(missing)}")
    return values


def _sandbox_url(name: str, url: str) -> str:
    if not any(marker in url.lower() for marker in ("sandbox", "test", "localhost")):
        pytest.skip(f"{name} is not recognizably sandbox/test; refusing provider call")
    return url.rstrip("/")


@pytest.mark.asyncio
async def test_resident_stripe_account_access():
    key, = _required("PAYMENTS_API_KEY")
    if not key.startswith("sk_test_"):
        pytest.skip("PAYMENTS_API_KEY is not a Stripe test key; refusing provider call")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.stripe.com/v1/account",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert response.status_code == 200
    assert str(response.json().get("id", "")).startswith("acct_")


@pytest.mark.asyncio
async def test_platform_stripe_account_access():
    key, = _required("STRIPE_SECRET_KEY")
    if not key.startswith("sk_test_"):
        pytest.skip("STRIPE_SECRET_KEY is not a Stripe test key; refusing provider call")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.stripe.com/v1/account",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_plaid_link_token_contract():
    client_id, secret, base_url = _required(
        "PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_API_BASE_URL"
    )
    base_url = _sandbox_url("PLAID_API_BASE_URL", base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{base_url}/link/token/create",
            json={
                "client_id": client_id,
                "secret": secret,
                "user": {"client_user_id": f"smoke-{uuid.uuid4()}"},
                "client_name": "Portfolio Desk integration smoke",
                "products": ["transactions"],
                "country_codes": ["US"],
                "language": "en",
            },
        )
    assert response.status_code == 200
    assert response.json().get("link_token")


@pytest.mark.asyncio
async def test_qbo_read_only_company_query():
    token, realm_id, base_url = _required(
        "QBO_SANDBOX_ACCESS_TOKEN", "QBO_SANDBOX_REALM_ID", "QBO_API_BASE_URL"
    )
    base_url = _sandbox_url("QBO_API_BASE_URL", base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{base_url}/{realm_id}/query",
            params={"query": "SELECT * FROM CompanyInfo", "minorversion": "70"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    assert response.status_code == 200
    assert response.json().get("QueryResponse", {}).get("CompanyInfo")


@pytest.mark.asyncio
async def test_screening_documented_health_endpoint():
    key, health_url = _required("SCREENING_API_KEY", "SCREENING_HEALTH_URL")
    health_url = _sandbox_url("SCREENING_HEALTH_URL", health_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            health_url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
    assert 200 <= response.status_code < 300


@pytest.mark.asyncio
async def test_oidc_discovery_document():
    issuer, = _required("SSO_SANDBOX_ISSUER")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        response = await client.get(
            f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        )
    assert response.status_code == 200
    document = response.json()
    assert str(document.get("issuer", "")).rstrip("/") == issuer.rstrip("/")
    assert all(document.get(field) for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"))
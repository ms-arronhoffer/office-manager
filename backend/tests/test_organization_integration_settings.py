"""Tenant integration configuration contracts and isolation tests."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.models.organization import Organization
from app.models.organization_integration_config import OrganizationIntegrationConfig
from app.models.user import User
from app.services import integration_readiness
from app.services import organization_integration_settings as subject
from app.services.bank_feed.plaid_client import PlaidClient
from app.utils.crypto import decrypt_secret, encrypt_secret
from tests.conftest import auth_headers


def test_provider_validation_rejects_mismatched_stripe_modes():
    with pytest.raises(ValueError, match="modes must match"):
        subject.validate_provider_settings(
            "resident_payments",
            {"provider": "stripe", "publishable_key": "pk_live_public"},
            "sk_test_secret",
        )


def test_plaid_environment_derives_and_validates_base_url():
    result = subject.validate_provider_settings(
        "plaid",
        {"client_id": "client", "environment": "sandbox", "country_codes": ["us", "CA"]},
        "secret",
    )
    assert result["api_base_url"] == "https://sandbox.plaid.com"
    assert result["country_codes"] == ["US", "CA"]
    with pytest.raises(ValueError, match="must match"):
        subject.validate_provider_settings(
            "plaid",
            {"client_id": "client", "environment": "production", "api_base_url": "https://sandbox.plaid.com"},
            "secret",
        )


def test_safe_config_masks_encrypted_secret_and_settings_are_immutable():
    with patch.object(settings, "APP_ENV", "test"):
        encrypted = encrypt_secret("sk_test_never-return")
    row = OrganizationIntegrationConfig(
        organization_id=uuid.uuid4(), provider="resident_payments", is_enabled=True,
        secret_encrypted=encrypted,
        settings_json={"provider": "stripe", "publishable_key": "pk_test_public", "api_url": "https://api.stripe.com/v1/payment_intents"},
    )
    resolved = subject._from_row("resident_payments", row)
    safe = subject.safe_config("resident_payments", resolved, row)
    assert decrypt_secret(encrypted) == "sk_test_never-return"
    assert safe["secret_hint"].endswith("turn")
    assert "never-return" not in str(safe)
    with pytest.raises(Exception):
        resolved.api_url = "https://attacker.invalid"  # type: ignore[misc]


def test_plaid_client_uses_explicit_tenant_credentials():
    config = subject.PlaidSettings(
        client_id="tenant-client", secret="tenant-secret", environment="sandbox",
        api_base_url="https://sandbox.plaid.com", country_codes=("US",), redirect_uri="",
        timeout_seconds=10, is_enabled=True, source="tenant",
    )
    client = PlaidClient(config=config)
    assert client.config.client_id == "tenant-client"
    assert client.config.secret == "tenant-secret"


@pytest.mark.asyncio
async def test_plaid_verification_is_safe_and_never_fabricates_success():
    config = subject.PlaidSettings(
        client_id="tenant-client", secret="tenant-secret", environment="sandbox",
        api_base_url="https://sandbox.plaid.com", country_codes=("US",), redirect_uri="",
        timeout_seconds=10, is_enabled=True, source="tenant",
    )
    with patch(
        "app.services.integration_readiness.PlaidClient.get_institutions",
        new=AsyncMock(return_value={"institutions": []}),
    ) as get_institutions:
        result = await integration_readiness.verify_plaid(config)
    assert result["ok"] is True
    get_institutions.assert_awaited_once_with(count=1)

    from app.services.bank_feed.plaid_client import PlaidApiError
    with patch(
        "app.services.integration_readiness.PlaidClient.get_institutions",
        new=AsyncMock(side_effect=PlaidApiError("invalid credentials")),
    ):
        result = await integration_readiness.verify_plaid(config)
    assert result["ok"] is False
    assert "invalid credentials" in result["error"]


@pytest.mark.asyncio
async def test_resolver_never_uses_tenant_a_row_for_tenant_b(db_session):
    org_a = Organization(name="Tenant A", slug="tenant-a")
    org_b = Organization(name="Tenant B", slug="tenant-b")
    db_session.add_all([org_a, org_b])
    await db_session.flush()
    db_session.add(OrganizationIntegrationConfig(
        organization_id=org_a.id, provider="plaid", is_enabled=True,
        secret_encrypted=encrypt_secret("tenant-a-secret"),
        settings_json={"client_id": "tenant-a-client", "environment": "sandbox", "api_base_url": "https://sandbox.plaid.com", "country_codes": ["US"], "redirect_uri": ""},
    ))
    await db_session.commit()
    with patch.object(settings, "PLAID_CLIENT_ID", "legacy-client"), patch.object(settings, "PLAID_SECRET", "legacy-secret"):
        resolved_a = await subject.resolve(db_session, org_a.id, "plaid")
        resolved_b = await subject.resolve(db_session, org_b.id, "plaid")
    assert resolved_a.client_id == "tenant-a-client"
    assert resolved_a.source == "tenant"
    assert resolved_b.client_id == "legacy-client"
    assert resolved_b.source == "legacy_env"


@pytest.mark.asyncio
async def test_readiness_excludes_platform_stripe(db_session):
    org = Organization(name="Readiness Tenant", slug="readiness-tenant")
    db_session.add(org)
    await db_session.commit()
    result = await integration_readiness.get_readiness(db_session, org.id)
    assert "platform_stripe" not in {item["provider"] for item in result}
    assert {"resident_payments", "screening", "plaid"}.issubset(
        {item["provider"] for item in result}
    )


@pytest.mark.asyncio
async def test_config_api_requires_admin_and_scopes_to_user_org(client, db_session):
    org = Organization(name="API Tenant", slug="api-tenant")
    db_session.add(org)
    await db_session.flush()
    admin = User(email="integration-admin@test.com", display_name="Admin", role="admin", organization_id=org.id, is_active=True)
    viewer = User(email="integration-viewer@test.com", display_name="Viewer", role="viewer", organization_id=org.id, is_active=True)
    db_session.add_all([admin, viewer])
    await db_session.commit()
    denied = await client.get(
        "/api/v1/integrations/config/plaid", headers=auth_headers(viewer)
    )
    assert denied.status_code == 403
    saved = await client.put(
        "/api/v1/integrations/config/plaid",
        headers=auth_headers(admin),
        json={"is_enabled": True, "secret": "tenant-secret", "settings": {"client_id": "tenant-client", "environment": "sandbox", "country_codes": ["US"]}},
    )
    assert saved.status_code == 200
    assert saved.json()["secret_hint"].endswith("cret")
    assert "tenant-secret" not in saved.text

    disconnected = await client.delete(
        "/api/v1/integrations/config/plaid", headers=auth_headers(admin)
    )
    assert disconnected.status_code == 204
    after_disconnect = await client.get(
        "/api/v1/integrations/config/plaid", headers=auth_headers(admin)
    )
    assert after_disconnect.status_code == 200
    assert after_disconnect.json()["source"] == "tenant"
    assert after_disconnect.json()["is_enabled"] is False
    assert after_disconnect.json()["secret_hint"] is None
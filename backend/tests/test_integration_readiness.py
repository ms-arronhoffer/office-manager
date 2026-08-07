"""Fixture-free readiness and safe-verification contract tests."""
import httpx
import pytest

from app.services import integration_readiness
from app.services.organization_integration_settings import (
    ResidentPaymentsSettings,
    ScreeningSettings,
)


def payment_settings() -> ResidentPaymentsSettings:
    return ResidentPaymentsSettings(
        provider="stripe",
        secret_api_key="sk_test_do-not-return",
        publishable_key="pk_test_public",
        api_url="https://api.stripe.com/v1/payment_intents",
        is_enabled=True,
        source="tenant",
    )


def screening_settings(*, health_url: str) -> ScreeningSettings:
    return ScreeningSettings(
        provider_name="sandbox-screening",
        api_key="screen-secret",
        api_url="https://screen.example.test/v1/reports",
        health_url=health_url,
        poll_attempts=5,
        poll_interval_seconds=0,
        is_enabled=True,
        source="tenant",
    )


@pytest.mark.asyncio
async def test_stripe_account_verification_is_get_only_and_redacts_secret():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "acct_sandbox", "charges_enabled": True})

    result = await integration_readiness.verify_resident_payments(
        payment_settings(), transport=httpx.MockTransport(handler)
    )

    assert result == {
        "provider": "resident_payments",
        "ok": True,
        "verification_supported": True,
        "error": None,
    }
    assert [(request.method, str(request.url)) for request in requests] == [
        ("GET", "https://api.stripe.com/v1/account")
    ]
    assert "sk_test_do-not-return" not in str(result)


@pytest.mark.asyncio
async def test_stripe_error_shape_is_actionable_without_echoing_body():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401, json={"error": {"message": "bad sk_test_do-not-return"}}
        )
    )
    result = await integration_readiness.verify_resident_payments(
        payment_settings(), transport=transport
    )
    assert result["ok"] is False
    assert result["error"] == "Stripe account verification returned HTTP 401."
    assert "sk_test_do-not-return" not in str(result)


@pytest.mark.asyncio
async def test_screening_refuses_to_invent_health_endpoint():
    result = await integration_readiness.verify_screening(
        screening_settings(health_url="")
    )
    assert result["verification_supported"] is False
    assert "sandbox report" in result["error"]


@pytest.mark.asyncio
async def test_screening_health_contract_is_non_mutating_get():
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(204)

    result = await integration_readiness.verify_screening(
        screening_settings(health_url="https://screen.example.test/v1/health"),
        transport=httpx.MockTransport(handler),
    )
    assert result["ok"] is True
    assert methods == ["GET"]
    assert "screen-secret" not in str(result)
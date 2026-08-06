"""Fixture-free readiness and safe-verification contract tests."""
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.services import integration_readiness


@pytest.mark.asyncio
async def test_stripe_account_verification_is_get_only_and_redacts_secret():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "acct_sandbox", "charges_enabled": True})

    with (
        patch.object(settings, "PAYMENTS_PROVIDER", "stripe"),
        patch.object(settings, "PAYMENTS_API_KEY", "sk_test_do-not-return"),
        patch.object(settings, "PAYMENTS_API_URL", "https://api.stripe.com/v1/payment_intents"),
    ):
        result = await integration_readiness.verify_resident_payments(
            transport=httpx.MockTransport(handler)
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
    with (
        patch.object(settings, "PAYMENTS_PROVIDER", "stripe"),
        patch.object(settings, "PAYMENTS_API_KEY", "sk_test_do-not-return"),
    ):
        result = await integration_readiness.verify_resident_payments(transport=transport)
    assert result["ok"] is False
    assert result["error"] == "Stripe account verification returned HTTP 401."
    assert "sk_test_do-not-return" not in str(result)


@pytest.mark.asyncio
async def test_screening_refuses_to_invent_health_endpoint():
    with patch.object(settings, "SCREENING_HEALTH_URL", ""):
        result = await integration_readiness.verify_screening()
    assert result["verification_supported"] is False
    assert "sandbox report" in result["error"]


@pytest.mark.asyncio
async def test_screening_health_contract_is_non_mutating_get():
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(204)

    with (
        patch.object(settings, "SCREENING_API_KEY", "screen-secret"),
        patch.object(settings, "SCREENING_HEALTH_URL", "https://screen.example.test/v1/health"),
    ):
        result = await integration_readiness.verify_screening(
            transport=httpx.MockTransport(handler)
        )
    assert result["ok"] is True
    assert methods == ["GET"]
    assert "screen-secret" not in str(result)
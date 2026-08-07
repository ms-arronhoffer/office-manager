"""Fixture-free tests for resident payment configuration and token validation."""

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers.resident_portal import _payment_config, _validate_processor_token
from app.services import resident_ach_service
from app.services.organization_integration_settings import PlaidSettings, ResidentPaymentsSettings
from app.utils import payment_processor


def test_payment_config_requires_secret_and_publishable_keys():
    with (
        patch.object(settings, "PAYMENTS_PROVIDER", "stripe"),
        patch.object(settings, "PAYMENTS_API_KEY", "sk_test_secret"),
        patch.object(settings, "PAYMENTS_PUBLISHABLE_KEY", ""),
    ):
        config = _payment_config()

    assert config.configured is False
    assert config.provider == "stripe"
    assert config.publishable_key == ""
    assert not hasattr(config, "api_key")


def test_payment_config_returns_publishable_key_when_fully_configured():
    with (
        patch.object(settings, "PAYMENTS_API_KEY", "sk_test_secret"),
        patch.object(settings, "PAYMENTS_PUBLISHABLE_KEY", "pk_test_public"),
    ):
        config = _payment_config()

    assert config.configured is True
    assert config.publishable_key == "pk_test_public"


@pytest.mark.parametrize("token", ["tok_visa", "4242 4242 4242 4242", "pm_"])
def test_stripe_rejects_non_payment_method_tokens(token):
    with pytest.raises(HTTPException) as exc_info:
        _validate_processor_token(token, "stripe")

    assert exc_info.value.status_code == 422


def test_stripe_accepts_payment_method_id():
    _validate_processor_token("pm_test_visa", "stripe")


def test_generic_provider_preserves_opaque_tokens():
    _validate_processor_token("provider-token-123", "generic")


class _PaymentClient:
    def __init__(self, response: httpx.Response, recorder: list):
        self.response = response
        self.recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, **kwargs):
        self.recorder.append((url, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_payment_intent_contract_uses_form_body_and_idempotency(monkeypatch):
    recorder: list = []
    response = httpx.Response(200, json={"id": "pi_123", "status": "succeeded"})
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kwargs: _PaymentClient(response, recorder)
    )
    result = await payment_processor.charge_payment(
        Decimal("12.34"),
        method="card",
        payment_token="pm_contract",
        idempotency_key="idem-contract",
        config=_payment_settings(),
    )

    assert result.captured is True
    assert result.processor_ref == "pi_123"
    url, request = recorder[0]
    assert url.endswith("/v1/payment_intents")
    assert request["data"]["amount"] == 1234
    assert request["data"]["payment_method"] == "pm_contract"
    assert request["headers"]["Idempotency-Key"] == "idem-contract"


@pytest.mark.asyncio
async def test_payment_intent_error_contract_surfaces_provider_message(monkeypatch):
    response = httpx.Response(
        402, json={"error": {"type": "card_error", "message": "Card declined"}}
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kwargs: _PaymentClient(response, [])
    )
    result = await payment_processor.charge_payment(
        Decimal("5.00"),
        method="card",
        payment_token="pm_declined",
        config=_payment_settings(),
    )
    assert result.captured is False
    assert result.status == "failed"
    assert result.detail == "Card declined"


def _payment_settings(secret: str = "sk_test_contract") -> ResidentPaymentsSettings:
    return ResidentPaymentsSettings(
        provider="stripe",
        secret_api_key=secret,
        publishable_key="pk_test_contract" if "test" in secret else "pk_live_contract",
        api_url="https://api.stripe.test/v1/payment_intents",
        is_enabled=True,
        source="tenant",
    )


def _plaid_settings(environment: str = "sandbox") -> PlaidSettings:
    return PlaidSettings(
        client_id="client",
        secret="secret",
        environment=environment,
        api_base_url=f"https://{environment}.plaid.com",
        country_codes=("US",),
        redirect_uri="",
        timeout_seconds=10,
        is_enabled=True,
        source="tenant",
        resident_ach_enabled=True,
    )


def test_ach_capability_rejects_plaid_stripe_mode_mismatch():
    capability = resident_ach_service.ach_capability(
        _plaid_settings("production"), _payment_settings("sk_test_contract")
    )
    assert capability.available is False
    assert capability.reason == "Plaid and Stripe modes do not match."


@pytest.mark.asyncio
async def test_stripe_source_attach_contract_uses_btok_without_secret_leak(monkeypatch):
    recorder: list = []
    response = httpx.Response(
        200,
        json={"id": "ba_source", "bank_name": "Test Bank", "last4": "6789"},
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kwargs: _PaymentClient(response, recorder)
    )
    source = await resident_ach_service.attach_bank_source(
        _payment_settings(),
        customer_id="cus_resident",
        bank_account_token="btok_plaid",
        idempotency_key="attach-once",
    )
    assert source["id"] == "ba_source"
    url, request = recorder[0]
    assert url.endswith("/v1/customers/cus_resident/sources")
    assert request["data"] == {"source": "btok_plaid"}
    assert request["headers"]["Idempotency-Key"] == "attach-once"
    assert "sk_test_contract" not in str(request["data"])


@pytest.mark.asyncio
async def test_ach_charge_uses_customer_source_api_and_stays_processing(monkeypatch):
    recorder: list = []
    response = httpx.Response(200, json={"id": "ch_ach", "status": "pending"})
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kwargs: _PaymentClient(response, recorder)
    )
    result = await payment_processor.charge_payment(
        Decimal("42.15"),
        method="ach",
        payment_token="ba_source",
        stripe_customer_id="cus_resident",
        idempotency_key="ach-once",
        metadata={"resident_payment_attempt_id": "attempt-123"},
        config=_payment_settings(),
    )
    assert result.status == "processing"
    assert result.captured is False
    assert result.processor_ref == "ch_ach"
    url, request = recorder[0]
    assert url.endswith("/v1/charges")
    assert request["data"]["customer"] == "cus_resident"
    assert request["data"]["source"] == "ba_source"
    assert request["data"]["metadata[resident_payment_attempt_id]"] == "attempt-123"
    assert "payment_method" not in request["data"]
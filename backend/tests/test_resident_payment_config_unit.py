"""Fixture-free tests for resident payment configuration and token validation."""

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers.resident_portal import _payment_config, _validate_processor_token
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
    with (
        patch.object(settings, "PAYMENTS_API_KEY", "sk_test_contract"),
        patch.object(settings, "PAYMENTS_API_URL", "https://api.stripe.test/v1/payment_intents"),
    ):
        result = await payment_processor.charge_payment(
            Decimal("12.34"),
            method="card",
            payment_token="pm_contract",
            idempotency_key="idem-contract",
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
    with patch.object(settings, "PAYMENTS_API_KEY", "sk_test_contract"):
        result = await payment_processor.charge_payment(
            Decimal("5.00"), method="card", payment_token="pm_declined"
        )
    assert result.captured is False
    assert result.status == "failed"
    assert result.detail == "Card declined"
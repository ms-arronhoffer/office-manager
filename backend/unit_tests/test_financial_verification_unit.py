from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import financial_verification_service as subject
from app.services.bank_feed.plaid_client import PlaidClient
from app.services.bank_feed.plaid_client import PlaidApiError
from app.services.organization_integration_settings import PlaidSettings
from app.utils.crypto import encrypt_secret


def test_invitation_token_is_one_way_sha256():
    raw = "private-invitation-token"
    digest = subject.hash_invitation_token(raw)
    assert digest == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in digest
    assert len(digest) == 64


def test_identity_matching_persists_only_boolean_and_score():
    response = {"accounts": [{"owners": [{
        "names": ["Jamie Applicant"],
        "emails": [{"data": "jamie@example.com"}],
        "phone_numbers": [{"data": "+1 555 222 3333"}],
        "addresses": [{"data": {"street": "never retain"}}],
    }]}]}
    matched, score = subject.identity_matches(
        response, name="Jamie Applicant", email="jamie@example.com", phone="5552223333"
    )
    assert matched is True
    assert score == 1.0
    assert isinstance((matched, score), tuple)


def test_auth_summary_discards_account_and_routing_numbers():
    raw = {
        "accounts": [{"account_id": "a1"}],
        "numbers": {"ach": [{"account_id": "a1", "account": "123456", "routing": "987654321"}]},
    }
    result = subject.auth_summary(raw)
    assert result == {"auth_available": True, "usable_account_count": 1}
    assert "123456" not in str(result)
    assert "987654321" not in str(result)


def test_balance_summary_is_aggregate_only():
    result = subject.balance_summary({"accounts": [
        {"account_id": "a1", "mask": "1111", "balances": {"available": 100, "current": 120}},
        {"account_id": "a2", "mask": "2222", "balances": {"available": 50, "current": 55}},
    ]})
    assert result == {
        "account_count": 2,
        "available_balance_total": Decimal("150"),
        "current_balance_total": Decimal("175"),
    }
    assert "1111" not in str(result)


def test_income_aggregation_is_bounded_and_conservative():
    result = subject.recurring_income_summary([
        {"date": "2026-05-01", "amount": -3000, "name": "Employer payroll", "category": ["Income"]},
        {"date": "2026-06-01", "amount": -3000, "name": "Employer payroll", "category": ["Income"]},
        {"date": "2026-06-15", "amount": -500, "name": "Venmo transfer", "category": ["Transfer"]},
        {"date": "2026-06-20", "amount": 100, "name": "Purchase refund", "category": ["Refund"]},
    ])
    assert result["recurring_income_monthly"] == Decimal("3000.00")
    assert result["income_months_observed"] == 2
    assert result["methodology_version"] == "plaid-credits-v1"
    assert "Employer payroll" not in str(result)


def test_recommendation_is_decision_support_with_reason_codes():
    decision, reasons = subject.recommendation(
        identity_match=False, ownership_match=False, auth_available=True, months_observed=1
    )
    assert decision == "review"
    assert reasons == ["identity_not_matched", "ownership_not_established", "limited_income_history"]
    assert "approve" not in decision and "deny" not in decision


def test_webhook_body_hash_uses_exact_bytes():
    body = b'{"item_id":"item-1","webhook_code":"ERROR"}'
    assert subject.webhook_body_hash(body) == hashlib.sha256(body).hexdigest()
    assert subject.webhook_body_hash(body + b" ") != subject.webhook_body_hash(body)


class _Response:
    status_code = 200

    def json(self):
        return {"ok": True, "link_token": "link-1"}


class _HttpClient:
    requests: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json):
        self.requests.append((url, json))
        return _Response()


@pytest.mark.asyncio
async def test_plaid_client_applicant_products_and_minimized_endpoints(monkeypatch):
    import httpx

    _HttpClient.requests.clear()
    monkeypatch.setattr(httpx, "AsyncClient", _HttpClient)
    config = PlaidSettings(
        client_id="client", secret="secret", environment="sandbox",
        api_base_url="https://sandbox.plaid.com", country_codes=("US",), redirect_uri="",
        timeout_seconds=10, is_enabled=True, source="tenant",
        webhook_url="https://example.com/webhook", applicant_verification_enabled=True,
    )
    client = PlaidClient(config=config)
    await client.create_link_token(
        client_user_id="application-id", client_name="Example Housing",
        products=["identity", "auth", "transactions"],
        webhook_url=config.webhook_url, user_email="jamie@example.com", legal_name="Jamie Applicant",
    )
    await client.get_identity("access")
    await client.get_auth("access")
    await client.get_balances("access")
    await client.get_transactions("access", start_date=date(2026, 5, 1), end_date=date(2026, 7, 31), count=125)
    paths = [url.rsplit("/", 2)[-2:] for url, _ in _HttpClient.requests]
    link_body = _HttpClient.requests[0][1]
    assert link_body["products"] == ["identity", "auth", "transactions"]
    assert link_body["webhook"] == "https://example.com/webhook"
    assert link_body["user"]["client_user_id"] == "application-id"
    assert ["identity", "get"] in paths
    assert ["auth", "get"] in paths
    assert ["balance", "get"] in paths
    assert ["transactions", "get"] in paths


@pytest.mark.asyncio
async def test_product_not_ready_retains_only_encrypted_token_for_webhook_resume(monkeypatch):
    class PendingClient:
        removed = False

        async def get_identity(self, _token):
            return {"accounts": [{"owners": [{"names": ["Jamie Applicant"], "emails": [], "phone_numbers": []}]}]}

        async def get_auth(self, _token):
            return {"accounts": [{"account_id": "a1"}], "numbers": {"ach": [{"account_id": "a1"}]}}

        async def get_balances(self, _token):
            return {"accounts": [{"balances": {"available": 100, "current": 120}}]}

        async def get_transactions(self, _token, **_kwargs):
            raise PlaidApiError("Transactions are initializing", error_code="PRODUCT_NOT_READY")

        async def remove_item(self, _token):
            self.removed = True

    verification = SimpleNamespace(
        access_token_encrypted=encrypt_secret("access-secret"), status="linking",
        identity_match=None, ownership_match=None, account_count=None,
        available_balance_total=None, current_balance_total=None,
        recurring_income_monthly=None, income_months_observed=None,
        recommendation="unknown", summary_json={}, completed_at=None,
        last_error=None, disconnected_at=None,
    )
    application = SimpleNamespace(
        applicant_first_name="Jamie", applicant_last_name="Applicant",
        applicant_email="jamie@example.com", applicant_phone=None,
    )
    client = PendingClient()

    await subject.process_verification(verification, application, client)

    assert verification.status == "processing"
    assert verification.summary_json["reason_codes"] == ["income_processing"]
    assert verification.access_token_encrypted is not None
    assert client.removed is False
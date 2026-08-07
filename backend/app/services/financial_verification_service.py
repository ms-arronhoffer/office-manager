"""Minimized Plaid applicant verification processing."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from jose import jwt

from app.utils.crypto import decrypt_secret, encrypt_secret

CONSENT_VERSION = "2026-08-07"
CONSENT_TEXT = (
    "I authorize this rental application financial verification using Plaid. "
    "Plaid will securely connect to my selected financial institution. Portfolio Desk and the requesting organization do not receive my bank credentials. "
    "The checks are account ownership and applicant identity matching, account availability, aggregate current and available balances, and a 90-day recurring income estimate. "
    "Account and routing numbers, raw identity details, and transaction rows are not retained. The result supports staff review and does not automatically approve or deny my application."
)
REQUESTED_CHECKS = [
    "Account ownership and applicant identity match",
    "Connected account availability",
    "Aggregate current and available balances",
    "Recurring income estimate from up to 90 days of transactions",
]
INCOME_METHOD_VERSION = "plaid-credits-v1"
_INCOME_HINTS = ("payroll", "salary", "direct deposit", "income", "wages")
_EXCLUDED_HINTS = ("transfer", "venmo", "cash app", "zelle", "refund")


def now() -> datetime:
    return datetime.now(timezone.utc)


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def webhook_body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def verify_webhook_jwt(body: bytes, verification_header: str, client) -> dict[str, Any]:
    if not verification_header:
        raise ValueError("Missing Plaid webhook verification header.")
    header = jwt.get_unverified_header(verification_header)
    if header.get("alg") != "ES256" or not header.get("kid"):
        raise ValueError("Unsupported Plaid webhook signature.")
    key_response = await client.get_webhook_verification_key(header["kid"])
    key = key_response.get("key") or {}
    claims = jwt.decode(
        verification_header,
        key,
        algorithms=["ES256"],
        options={"verify_aud": False},
    )
    issued_at = claims.get("iat")
    if not isinstance(issued_at, (int, float)):
        raise ValueError("Plaid webhook signature is missing its issued-at time.")
    age_seconds = now().timestamp() - float(issued_at)
    if age_seconds < -30 or age_seconds > 300:
        raise ValueError("Plaid webhook signature is outside the accepted time window.")
    if claims.get("request_body_sha256") != webhook_body_hash(body):
        raise ValueError("Plaid webhook body hash mismatch.")
    return json.loads(body)


def normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _phone_matches(target: str, candidate: str) -> bool:
    return bool(target and candidate and target[-10:] == candidate[-10:])


def identity_matches(identity_response: dict[str, Any], *, name: str, email: str, phone: str | None) -> tuple[bool, float]:
    target_name, target_email, target_phone = normalize(name), normalize(email), normalize(phone)
    best = 0.0
    for account in identity_response.get("accounts", []):
        for owner in account.get("owners", []):
            owner_names = [normalize(value) for value in owner.get("names", [])]
            owner_emails = [normalize(item.get("data")) for item in owner.get("emails", [])]
            owner_phones = [normalize(item.get("data")) for item in owner.get("phone_numbers", [])]
            score = 0.6 if target_name and target_name in owner_names else 0.0
            score += 0.25 if target_email and target_email in owner_emails else 0.0
            score += 0.15 if any(_phone_matches(target_phone, value) for value in owner_phones) else 0.0
            best = max(best, score)
    return best >= 0.6, round(best, 2)


def auth_summary(auth_response: dict[str, Any]) -> dict[str, Any]:
    account_ids = {str(account.get("account_id")) for account in auth_response.get("accounts", []) if account.get("account_id")}
    number_ids = {
        str(item.get("account_id"))
        for group in auth_response.get("numbers", {}).values()
        for item in (group if isinstance(group, list) else [])
        if item.get("account_id")
    }
    return {"auth_available": bool(account_ids & number_ids), "usable_account_count": len(account_ids & number_ids)}


def balance_summary(balance_response: dict[str, Any]) -> dict[str, Any]:
    accounts = balance_response.get("accounts", [])
    available = sum((Decimal(str(a.get("balances", {}).get("available"))) for a in accounts if a.get("balances", {}).get("available") is not None), Decimal("0"))
    current = sum((Decimal(str(a.get("balances", {}).get("current"))) for a in accounts if a.get("balances", {}).get("current") is not None), Decimal("0"))
    return {"account_count": len(accounts), "available_balance_total": available, "current_balance_total": current}


def recurring_income_summary(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    by_month: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for transaction in transactions:
        if not isinstance(transaction, dict):
            continue
        name = str(transaction.get("name") or "").casefold()
        raw_categories = transaction.get("category") or []
        if isinstance(raw_categories, str):
            raw_categories = [raw_categories]
        categories = " ".join(str(value) for value in raw_categories).casefold()
        try:
            amount = Decimal(str(transaction.get("amount", 0) or 0))
        except (ArithmeticError, ValueError):
            continue
        if amount >= 0 or any(term in name for term in _EXCLUDED_HINTS):
            continue
        if not (any(term in name for term in _INCOME_HINTS) or "income" in categories or "payroll" in categories):
            continue
        month = str(transaction.get("date", ""))[:7]
        if len(month) == 7:
            by_month[month] += -amount
    observed = len(by_month)
    estimate = (sum(by_month.values(), Decimal("0")) / observed).quantize(Decimal("0.01")) if observed else Decimal("0")
    return {"recurring_income_monthly": estimate, "income_months_observed": observed, "methodology_version": INCOME_METHOD_VERSION}


def recommendation(*, identity_match: bool, ownership_match: bool, auth_available: bool, months_observed: int) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not identity_match:
        reasons.append("identity_not_matched")
    if not ownership_match:
        reasons.append("ownership_not_established")
    if not auth_available:
        reasons.append("auth_data_unavailable")
    if months_observed < 2:
        reasons.append("limited_income_history")
    if not auth_available:
        return "insufficient", reasons
    if reasons:
        return "review", reasons
    return "verified", ["identity_ownership_and_history_supported"]


async def collect_transactions(client, access_token: str) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=90)
    rows: list[dict[str, Any]] = []
    offset = 0
    for _ in range(4):
        page = await client.get_transactions(access_token, start_date=start, end_date=end, count=125, offset=offset)
        batch = page.get("transactions", [])
        rows.extend(batch)
        offset += len(batch)
        if not batch or offset >= min(int(page.get("total_transactions", offset)), 500):
            break
    return rows


async def process_verification(verification, application, client) -> None:
    access_token = decrypt_secret(verification.access_token_encrypted)
    verification.status = "processing"
    disconnect_item = True
    try:
        identity, auth, balances = await client.get_identity(access_token), await client.get_auth(access_token), await client.get_balances(access_token)
        identity_match, match_score = identity_matches(identity, name=f"{application.applicant_first_name} {application.applicant_last_name}", email=application.applicant_email, phone=application.applicant_phone)
        auth_result = auth_summary(auth)
        balance_result = balance_summary(balances)
        verification.identity_match = identity_match
        verification.ownership_match = identity_match and auth_result["auth_available"]
        verification.account_count = balance_result["account_count"]
        verification.available_balance_total = balance_result["available_balance_total"]
        verification.current_balance_total = balance_result["current_balance_total"]
        try:
            transactions = await collect_transactions(client, access_token)
        except Exception as exc:
            if getattr(exc, "error_code", None) == "PRODUCT_NOT_READY":
                disconnect_item = False
                verification.status = "processing"
                verification.last_error = None
                verification.summary_json = {
                    "identity_match_score": match_score,
                    "auth_available": auth_result["auth_available"],
                    "income_methodology_version": INCOME_METHOD_VERSION,
                    "reason_codes": ["income_processing"],
                    "decision_support_only": True,
                }
                return
            raise
        income_result = recurring_income_summary(transactions)
        decision, reasons = recommendation(identity_match=identity_match, ownership_match=verification.ownership_match, auth_available=auth_result["auth_available"], months_observed=income_result["income_months_observed"])
        verification.recurring_income_monthly = income_result["recurring_income_monthly"]
        verification.income_months_observed = income_result["income_months_observed"]
        verification.recommendation = decision
        verification.summary_json = {"identity_match_score": match_score, "auth_available": auth_result["auth_available"], "income_methodology_version": INCOME_METHOD_VERSION, "reason_codes": reasons, "decision_support_only": True}
        verification.status = "completed"
        verification.completed_at = now()
        verification.last_error = None
    except Exception as exc:
        verification.status = "error"
        verification.last_error = getattr(exc, "error_code", None) or type(exc).__name__
        raise
    finally:
        if disconnect_item:
            try:
                await client.remove_item(access_token)
            except Exception:
                # Provider cleanup failure must not retain the local access token.
                # The Item id remains available for support-assisted revocation.
                pass
            finally:
                verification.access_token_encrypted = None
                verification.disconnected_at = now()
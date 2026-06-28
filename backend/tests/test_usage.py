"""Tests for usage metering: token capture, aggregation, and tier limits.

Covers:
* AI token parsing from Gemini ``usageMetadata`` and persistence per org.
* The super-admin usage aggregation endpoints (feature adoption + tokens).
* ``is_over_limit`` for the new monthly token limit keys.
* Over-limit enforcement on the AI endpoints (HTTP 429).
"""
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.services import ai_service, entitlements as ent, usage_service
from tests.conftest import auth_headers


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _org_user(db_session, plan: str, email: str):
    org = Organization(name=f"Org {email}", slug=f"org-{email[:6]}", plan=plan)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return org, user


async def _super_admin(db_session, email: str = "root-usage@test.com") -> User:
    user = User(
        email=email,
        display_name="Root",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        is_super_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _doc():
    return ("lease.txt", io.BytesIO(b"Lessor: Acme."), "text/plain")


# ── Token parsing from usageMetadata ──────────────────────────────────────────

def test_record_usage_metadata_reads_prompt_and_candidate_tokens():
    ai_service.reset_token_usage()
    ai_service._record_usage_metadata(
        {"usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 45}}
    )
    assert ai_service.collect_token_usage() == (120, 45)


def test_record_usage_metadata_falls_back_to_total_minus_prompt():
    ai_service.reset_token_usage()
    ai_service._record_usage_metadata(
        {"usageMetadata": {"promptTokenCount": 30, "totalTokenCount": 50}}
    )
    # candidates omitted -> total - prompt
    assert ai_service.collect_token_usage() == (30, 20)


def test_collect_token_usage_defaults_to_zero():
    ai_service.reset_token_usage()
    assert ai_service.collect_token_usage() == (0, 0)


@pytest.mark.asyncio
async def test_ai_call_persists_token_usage_per_org(client, db_session, monkeypatch):
    """A parse call records a usage event with the tokens the model reported."""
    org, user = await _org_user(db_session, "pro", "tok@test.com")

    async def fake_parse(content, mime_type, *, text_content=None):
        # Simulate the provider reporting token usage mid-call.
        ai_service.record_token_usage(100, 40)
        return {"lessor_name": "Acme"}

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post(
        "/api/v1/ai/leases/parse", headers=auth_headers(user), files={"file": _doc()}
    )
    assert resp.status_code == 200, resp.text

    rows = (
        await db_session.execute(
            select(UsageEvent).where(UsageEvent.organization_id == org.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].feature == "ai_lease_parse"
    assert rows[0].input_tokens == 100
    assert rows[0].output_tokens == 40


# ── Tier limit catalog + is_over_limit ────────────────────────────────────────

def test_token_limits_present_in_catalog():
    assert "monthly_ai_input_tokens" in ent.LIMIT_KEYS
    assert "monthly_ai_output_tokens" in ent.LIMIT_KEYS
    assert "monthly_ai_input_tokens" in ent.OVERRIDE_KEYS
    assert ent.PLAN_CATALOG["enterprise"]["monthly_ai_input_tokens"] is None
    assert ent.PLAN_CATALOG["starter"]["monthly_ai_input_tokens"] > 0


def test_is_over_limit_for_token_keys():
    starter = Organization(name="s", slug="s", plan="starter")
    enterprise = Organization(name="e", slug="e", plan="enterprise")
    limit = ent.PLAN_CATALOG["starter"]["monthly_ai_input_tokens"]
    assert ent.is_over_limit("monthly_ai_input_tokens", limit, starter) is True
    assert ent.is_over_limit("monthly_ai_input_tokens", limit - 1, starter) is False
    # Enterprise is unlimited -> never over.
    assert ent.is_over_limit("monthly_ai_input_tokens", 10**9, enterprise) is False


def test_token_limit_override_raises_cap():
    org = Organization(
        name="o", slug="o", plan="starter",
        entitlement_overrides={"monthly_ai_input_tokens": 999999},
    )
    assert ent.get_limit(org, "monthly_ai_input_tokens") == 999999


# ── Over-limit enforcement ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_request_blocked_when_over_token_budget(client, db_session, monkeypatch):
    org, user = await _org_user(db_session, "starter", "over@test.com")
    limit = ent.PLAN_CATALOG["starter"]["monthly_ai_input_tokens"]
    db_session.add(
        UsageEvent(
            organization_id=org.id,
            feature="ai_lease_parse",
            quantity=1,
            input_tokens=limit,
            output_tokens=0,
            period_month=usage_service.current_period(),
        )
    )
    await db_session.commit()

    async def fake_parse(content, mime_type, *, text_content=None):  # pragma: no cover
        return {"lessor_name": "Acme"}

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post(
        "/api/v1/ai/leases/parse", headers=auth_headers(user), files={"file": _doc()}
    )
    assert resp.status_code == 429, resp.text
    assert "token limit" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ai_request_allowed_when_under_budget(client, db_session, monkeypatch):
    org, user = await _org_user(db_session, "starter", "under@test.com")
    db_session.add(
        UsageEvent(
            organization_id=org.id,
            feature="ai_lease_parse",
            quantity=1,
            input_tokens=10,
            output_tokens=0,
            period_month=usage_service.current_period(),
        )
    )
    await db_session.commit()

    async def fake_parse(content, mime_type, *, text_content=None):
        return {"lessor_name": "Acme"}

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post(
        "/api/v1/ai/leases/parse", headers=auth_headers(user), files={"file": _doc()}
    )
    assert resp.status_code == 200, resp.text


# ── Admin aggregation endpoints ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feature_adoption_endpoint(client, db_session):
    org, _ = await _org_user(db_session, "pro", "adopt@test.com")
    period = usage_service.current_period()
    db_session.add_all([
        UsageEvent(organization_id=org.id, feature="ai_summary", quantity=3,
                   input_tokens=300, output_tokens=120, period_month=period),
        UsageEvent(organization_id=org.id, feature="waiver_sent", quantity=1,
                   input_tokens=0, output_tokens=0, period_month=period),
    ])
    await db_session.commit()
    root = await _super_admin(db_session)

    resp = await client.get("/admin/v1/usage/features", headers=auth_headers(root))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_feature = {f["feature"]: f for f in body["features"]}
    assert by_feature["ai_summary"]["events"] == 3
    assert by_feature["ai_summary"]["org_count"] == 1
    assert by_feature["ai_summary"]["input_tokens"] == 300
    # A tracked feature with no events is flagged as a removal candidate.
    assert by_feature["ai_draft"]["events"] == 0
    assert by_feature["ai_draft"]["removal_candidate"] is True


@pytest.mark.asyncio
async def test_platform_tokens_endpoint(client, db_session):
    org, _ = await _org_user(db_session, "pro", "plat@test.com")
    period = usage_service.current_period()
    db_session.add(
        UsageEvent(organization_id=org.id, feature="ai_summary", quantity=1,
                   input_tokens=500, output_tokens=200, period_month=period)
    )
    await db_session.commit()
    root = await _super_admin(db_session, "root-plat@test.com")

    resp = await client.get("/admin/v1/usage/tokens", headers=auth_headers(root))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["input_tokens"] == 500
    assert body["output_tokens"] == 200
    assert body["total_tokens"] == 700
    assert body["top_orgs"][0]["organization_id"] == str(org.id)
    assert body["top_orgs"][0]["total_tokens"] == 700


@pytest.mark.asyncio
async def test_org_usage_endpoint(client, db_session):
    org, _ = await _org_user(db_session, "starter", "orgusage@test.com")
    period = usage_service.current_period()
    db_session.add(
        UsageEvent(organization_id=org.id, feature="ai_lease_parse", quantity=2,
                   input_tokens=150, output_tokens=60, period_month=period)
    )
    await db_session.commit()
    root = await _super_admin(db_session, "root-org@test.com")

    resp = await client.get(f"/admin/v1/usage/orgs/{org.id}", headers=auth_headers(root))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current"]["input_tokens"] == 150
    assert body["current"]["output_tokens"] == 60
    assert body["current"]["total_tokens"] == 210
    assert body["input_token_limit"] == ent.PLAN_CATALOG["starter"]["monthly_ai_input_tokens"]
    assert body["by_feature"][0]["feature"] == "ai_lease_parse"


@pytest.mark.asyncio
async def test_usage_endpoints_require_super_admin(client, db_session):
    _, user = await _org_user(db_session, "pro", "noadmin@test.com")
    resp = await client.get("/admin/v1/usage/features", headers=auth_headers(user))
    assert resp.status_code == 403, resp.text


# ── AI status exposes token headroom ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_status_reports_token_headroom(client, db_session):
    org, user = await _org_user(db_session, "starter", "headroom@test.com")
    db_session.add(
        UsageEvent(organization_id=org.id, feature="ai_lease_parse", quantity=1,
                   input_tokens=25, output_tokens=5,
                   period_month=usage_service.current_period())
    )
    await db_session.commit()

    resp = await client.get("/api/v1/ai/status", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["input_tokens_used"] == 25
    assert body["output_tokens_used"] == 5
    assert body["input_token_limit"] == ent.PLAN_CATALOG["starter"]["monthly_ai_input_tokens"]
    assert body["token_limit_reached"] is False

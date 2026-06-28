"""Regression tests for the SLA analytics endpoint (/api/v1/reports/analytics/sla).

site_settings is keyed by organization_id (UUID), so the SLA threshold lookup
must query by organization_id rather than the legacy singleton ``id == 1``.
"""
import uuid

import pytest


async def _pro_headers(db_session, email):
    from app.auth.jwt_handler import create_access_token
    from app.auth.password import hash_password
    from app.models.organization import Organization
    from app.models.user import User

    org = Organization(name="SLA Org", slug=f"sla-{uuid.uuid4().hex[:8]}", plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email, display_name="U", password_hash=hash_password("x"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return org, {"Authorization": "Bearer " + token}


@pytest.mark.asyncio
async def test_sla_analytics_returns_default_thresholds_without_site_settings(client, db_session):
    """No site_settings row → falls back to default thresholds (no DB error)."""
    _org, headers = await _pro_headers(db_session, "slanodef@test.com")
    resp = await client.get("/api/v1/reports/analytics/sla", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sla_thresholds"] == {"high": 1, "medium": 3, "low": 7}


@pytest.mark.asyncio
async def test_sla_analytics_uses_org_site_settings(client, db_session):
    """SLA thresholds come from the requesting org's site_settings row."""
    from app.models.site_settings import SiteSettings

    org, headers = await _pro_headers(db_session, "slacustom@test.com")
    db_session.add(SiteSettings(
        organization_id=org.id,
        sla_high_days=2,
        sla_medium_days=5,
        sla_low_days=10,
    ))
    await db_session.commit()

    resp = await client.get("/api/v1/reports/analytics/sla", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sla_thresholds"] == {"high": 2, "medium": 5, "low": 10}

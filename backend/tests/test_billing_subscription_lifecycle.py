"""Tests for the org-facing subscription lifecycle: trial visibility, Starter
self-serve checkout, in-place plan switch (upgrade/downgrade), and
cancel/reactivate (access retained through end of paid period)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.password import hash_password
from app.config import settings
from app.models.organization import Organization
from app.models.user import User
from app.services import entitlements as ent
from tests.conftest import auth_headers


async def _make_org(db, slug):
    org = Organization(name="Other Co", slug=slug, plan="starter", is_active=True)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _org_admin(db, **org_kwargs):
    org_kwargs.setdefault("plan", "starter")
    org = Organization(name="Acme Co", slug=f"acme-{id(org_kwargs)}", is_active=True, **org_kwargs)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    u = User(
        email=f"admin{id(org_kwargs)}@test.com", display_name="Admin",
        password_hash=hash_password("pw12345678"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org.id,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return org, u


@pytest.fixture(autouse=True)
def _stripe_env(monkeypatch):
    """Enable billing via env fallback (no DB PlatformStripeConfig row needed)."""
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_STARTER", "price_starter")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO", "price_pro")
    monkeypatch.setattr(settings, "STRIPE_PRODUCT_ID_ENTERPRISE", "prod_enterprise")
    yield


# ─── Trial visibility ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_reports_active_trial(client, db_session):
    trial_end = datetime.now(timezone.utc) + timedelta(days=5)
    org, admin = await _org_admin(db_session, trial_ends_at=trial_end)

    r = await client.get("/api/v1/billing/subscription", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_trialing"] is True
    assert body["trial_days_remaining"] in (4, 5)
    assert body["trial_ends_at"] is not None


@pytest.mark.asyncio
async def test_subscription_not_trialing_once_subscribed(client, db_session):
    trial_end = datetime.now(timezone.utc) + timedelta(days=5)
    org, admin = await _org_admin(
        db_session, trial_ends_at=trial_end, stripe_subscription_id="sub_123",
    )

    r = await client.get("/api/v1/billing/subscription", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_trialing"] is False
    assert body["trial_days_remaining"] is None


# ─── Starter checkout ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_allows_starter_plan(client, db_session, monkeypatch):
    org, admin = await _org_admin(db_session)

    class _FakeSession:
        url = "https://checkout.stripe.com/session/xyz"

    monkeypatch.setattr(
        "stripe.checkout.Session.create", lambda **kwargs: _FakeSession()
    )

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin), json={"plan": "starter"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"] == "https://checkout.stripe.com/session/xyz"


# ─── In-place plan switch (upgrade/downgrade) ──────────────────────────────

@pytest.mark.asyncio
async def test_checkout_switches_existing_subscription_in_place(client, db_session, monkeypatch):
    org, admin = await _org_admin(
        db_session, plan="pro", stripe_subscription_id="sub_existing", payment_status="active",
    )

    fake_sub = {
        "items": {"data": [{"id": "si_1", "price": {"id": "price_starter", "product": "prod_x"}}]},
    }
    fake_updated = {
        "items": {"data": [{"price": {"id": "price_starter", "product": "prod_x"}}]},
        "cancel_at_period_end": False,
        "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=20)).timestamp()),
    }

    monkeypatch.setattr("stripe.Subscription.retrieve", lambda sub_id: fake_sub)
    modify_calls = []
    monkeypatch.setattr(
        "stripe.Subscription.modify",
        lambda sub_id, **kwargs: (modify_calls.append(kwargs), fake_updated)[1],
    )

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin), json={"plan": "starter"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checkout_url"] is None
    assert body["plan"] == "starter"
    assert modify_calls[0]["items"] == [{"id": "si_1", "price": "price_starter"}]

    await db_session.refresh(org)
    assert org.plan == "starter"
    assert org.payment_status == "active"
    assert org.is_active is True


# ─── Cancel / reactivate ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_subscription_schedules_at_period_end(client, db_session, monkeypatch):
    period_end = datetime.now(timezone.utc) + timedelta(days=12)
    org, admin = await _org_admin(
        db_session, plan="pro", stripe_subscription_id="sub_cancel", payment_status="active",
    )

    fake_sub = {
        "cancel_at_period_end": True,
        "current_period_end": int(period_end.timestamp()),
    }
    monkeypatch.setattr(
        "stripe.Subscription.modify", lambda sub_id, **kwargs: fake_sub
    )

    r = await client.post("/api/v1/billing/cancel", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cancel_at_period_end"] is True
    assert body["current_period_end"] is not None

    await db_session.refresh(org)
    assert org.cancel_at_period_end is True
    # Access is retained (org still active) until Stripe fires the
    # subscription.deleted webhook at the actual period end.
    assert org.is_active is True
    assert org.payment_status == "active"
    assert ent.org_access_state(org) == ent.ACCESS_OK


@pytest.mark.asyncio
async def test_reactivate_subscription_undoes_pending_cancellation(client, db_session, monkeypatch):
    org, admin = await _org_admin(
        db_session, plan="pro", stripe_subscription_id="sub_reactivate",
        payment_status="active", cancel_at_period_end=True,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=8),
    )

    fake_sub = {"cancel_at_period_end": False, "current_period_end": None}
    monkeypatch.setattr(
        "stripe.Subscription.modify", lambda sub_id, **kwargs: fake_sub
    )

    r = await client.post("/api/v1/billing/reactivate", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    assert r.json()["cancel_at_period_end"] is False

    await db_session.refresh(org)
    assert org.cancel_at_period_end is False


@pytest.mark.asyncio
async def test_reactivate_without_pending_cancellation_rejected(client, db_session):
    org, admin = await _org_admin(
        db_session, plan="pro", stripe_subscription_id="sub_noop", payment_status="active",
    )

    r = await client.post("/api/v1/billing/reactivate", headers=auth_headers(admin))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cancel_without_subscription_rejected(client, db_session):
    org, admin = await _org_admin(db_session)

    r = await client.post("/api/v1/billing/cancel", headers=auth_headers(admin))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cancel_surfaces_stripe_error_detail(client, db_session, monkeypatch):
    """When Stripe rejects the cancellation, the specific reason is returned to
    the client (instead of a generic, undiagnosable failure)."""
    import stripe

    org, admin = await _org_admin(
        db_session, plan="pro", stripe_subscription_id="sub_boom", payment_status="active",
    )

    def _raise(sub_id, **kwargs):
        raise stripe.error.InvalidRequestError("No such subscription: sub_boom", param="id")

    monkeypatch.setattr("stripe.Subscription.modify", _raise)

    r = await client.post("/api/v1/billing/cancel", headers=auth_headers(admin))
    assert r.status_code == 400
    assert "No such subscription" in r.json()["detail"]


# ─── Trial expiry enforcement (end-to-end) ──────────────────────────────────

@pytest.mark.asyncio
async def test_expired_trial_blocks_org_guarded_endpoint(client, db_session):
    """An org whose trial has ended without a paid subscription is locked out of
    org-guarded product surfaces with HTTP 403."""
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    org, admin = await _org_admin(db_session, trial_ends_at=expired)

    r = await client.get("/api/v1/offices", headers=auth_headers(admin))
    assert r.status_code == 403, r.text
    assert "trial" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_active_trial_allows_org_guarded_endpoint(client, db_session):
    """A trial still within its window retains full access to product surfaces."""
    future = datetime.now(timezone.utc) + timedelta(days=5)
    org, admin = await _org_admin(db_session, trial_ends_at=future)

    r = await client.get("/api/v1/offices", headers=auth_headers(admin))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_paid_subscription_restores_access_after_trial(client, db_session):
    """A paid subscription overrides an elapsed trial window and restores access."""
    expired = datetime.now(timezone.utc) - timedelta(days=10)
    org, admin = await _org_admin(
        db_session, trial_ends_at=expired, stripe_subscription_id="sub_paid",
    )

    r = await client.get("/api/v1/offices", headers=auth_headers(admin))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_expired_trial_can_still_reach_billing_to_upgrade(client, db_session):
    """A locked-out (trial-expired) org must still be able to authenticate and
    reach billing/organization endpoints so it can pay and restore access."""
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    org, admin = await _org_admin(db_session, trial_ends_at=expired)

    # Billing subscription view is intentionally not org-guarded.
    r = await client.get("/api/v1/billing/subscription", headers=auth_headers(admin))
    assert r.status_code == 200, r.text

    # Entitlements/access view reports the blocked, trial-expired state.
    r2 = await client.get(
        "/api/v1/organizations/me/entitlements", headers=auth_headers(admin)
    )
    assert r2.status_code == 200, r2.text
    access = r2.json()["access"]
    assert access["state"] == ent.ACCESS_TRIAL_EXPIRED
    assert access["blocked"] is True


# ─── Enterprise custom-priced activation ────────────────────────────────────

from app.models.enterprise_activation_code import EnterpriseActivationCode  # noqa: E402


async def _enterprise_code(db, org=None, **kwargs):
    kwargs.setdefault("stripe_price_id", "price_ent_custom")
    code = EnterpriseActivationCode(
        code=kwargs.pop("code", f"ENT-{id(kwargs)}"),
        organization_id=org.id if org else None,
        **kwargs,
    )
    db.add(code)
    await db.commit()
    await db.refresh(code)
    return code


@pytest.mark.asyncio
async def test_enterprise_activation_code_creates_checkout(client, db_session, monkeypatch):
    """A valid activation code resolves to a bespoke Enterprise price and starts
    a Checkout session; the code is marked redeemed by the org."""
    org, admin = await _org_admin(db_session)
    code = await _enterprise_code(db_session, org)

    monkeypatch.setattr(
        "stripe.Price.retrieve",
        lambda price_id: {"id": price_id, "product": "prod_enterprise"},
    )

    class _FakeSession:
        url = "https://checkout.stripe.com/session/ent"

    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kwargs: _FakeSession())

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": code.code},
    )
    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"] == "https://checkout.stripe.com/session/ent"

    await db_session.refresh(code)
    assert code.redeemed_at is not None
    assert code.redeemed_by_org_id == org.id


@pytest.mark.asyncio
async def test_enterprise_activation_switches_existing_subscription_in_place(client, db_session, monkeypatch):
    """A valid code on an org with a live subscription swaps the price in place
    and the plan resolves to enterprise (matched by product)."""
    org, admin = await _org_admin(
        db_session, plan="pro", stripe_subscription_id="sub_live", payment_status="active",
    )
    code = await _enterprise_code(db_session, org)

    monkeypatch.setattr(
        "stripe.Price.retrieve",
        lambda price_id: {"id": price_id, "product": "prod_enterprise"},
    )
    fake_sub = {"items": {"data": [{"id": "si_1", "price": {"id": "price_pro", "product": "prod_pro"}}]}}
    fake_updated = {
        "items": {"data": [{"price": {"id": "price_ent_custom", "product": "prod_enterprise"}}]},
        "cancel_at_period_end": False,
        "current_period_end": None,
    }
    monkeypatch.setattr("stripe.Subscription.retrieve", lambda sub_id: fake_sub)
    monkeypatch.setattr("stripe.Subscription.modify", lambda sub_id, **kwargs: fake_updated)

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": code.code},
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "enterprise"

    await db_session.refresh(org)
    assert org.plan == "enterprise"


@pytest.mark.asyncio
async def test_enterprise_raw_price_id_accepted_when_product_matches(client, db_session, monkeypatch):
    """A raw Stripe Price ID belonging to the Enterprise product is accepted
    even without an activation code."""
    org, admin = await _org_admin(db_session)

    monkeypatch.setattr(
        "stripe.Price.retrieve",
        lambda price_id: {"id": price_id, "product": "prod_enterprise"},
    )

    class _FakeSession:
        url = "https://checkout.stripe.com/session/raw"

    monkeypatch.setattr("stripe.checkout.Session.create", lambda **kwargs: _FakeSession())

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": "price_ent_direct"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"] == "https://checkout.stripe.com/session/raw"


@pytest.mark.asyncio
async def test_enterprise_price_from_wrong_product_rejected(client, db_session, monkeypatch):
    """A price whose product is not the Enterprise product is rejected so it can
    never over-grant the Enterprise tier."""
    org, admin = await _org_admin(db_session)
    code = await _enterprise_code(db_session, org, stripe_price_id="price_other")

    monkeypatch.setattr(
        "stripe.Price.retrieve",
        lambda price_id: {"id": price_id, "product": "prod_something_else"},
    )

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": code.code},
    )
    assert r.status_code == 400
    assert "not a valid Enterprise plan" in r.json()["detail"]


@pytest.mark.asyncio
async def test_enterprise_missing_code_rejected(client, db_session):
    """Selecting Enterprise without a code returns a 400."""
    org, admin = await _org_admin(db_session)

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin), json={"plan": "enterprise"},
    )
    assert r.status_code == 400
    assert "required" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_enterprise_unknown_code_rejected(client, db_session):
    """An unknown, non-price-id value is rejected as an invalid code."""
    org, admin = await _org_admin(db_session)

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": "TOTALLY-BOGUS"},
    )
    assert r.status_code == 400
    assert "Invalid Enterprise activation code" in r.json()["detail"]


@pytest.mark.asyncio
async def test_enterprise_code_bound_to_other_org_rejected(client, db_session, monkeypatch):
    """A code bound to a different org cannot be redeemed."""
    org, admin = await _org_admin(db_session)
    other = await _make_org(db_session, "other-bound-co")
    code = await _enterprise_code(db_session, other)  # bound to `other`

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": code.code},
    )
    assert r.status_code == 400
    assert "not valid for your organization" in r.json()["detail"]


@pytest.mark.asyncio
async def test_enterprise_code_already_used_by_other_org_rejected(client, db_session, monkeypatch):
    """A code already redeemed by another org is rejected as already used."""
    org, admin = await _org_admin(db_session)
    other = await _make_org(db_session, "other-used-co")
    code = await _enterprise_code(db_session, stripe_price_id="price_ent_custom")
    code.redeemed_at = datetime.now(timezone.utc)
    code.redeemed_by_org_id = other.id
    await db_session.commit()

    r = await client.post(
        "/api/v1/billing/checkout", headers=auth_headers(admin),
        json={"plan": "enterprise", "enterprise_code": code.code},
    )
    assert r.status_code == 400
    assert "already been used" in r.json()["detail"]


# ─── Super-admin activation code minting ────────────────────────────────────

async def _super_admin(db):
    sa = User(
        email=f"root{id(db)}@test.com", display_name="Root",
        password_hash=hash_password("pw12345678"),
        auth_provider="internal", role="admin", is_active=True, is_super_admin=True,
    )
    db.add(sa)
    await db.commit()
    await db.refresh(sa)
    return sa


@pytest.mark.asyncio
async def test_admin_can_mint_and_list_enterprise_code(client, db_session):
    sa = await _super_admin(db_session)

    r = await client.post(
        "/admin/v1/billing/enterprise-codes", headers=auth_headers(sa),
        json={"stripe_price_id": "price_ent_custom", "notes": "Acme negotiated deal"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stripe_price_id"] == "price_ent_custom"
    assert body["code"]
    assert body["is_active"] is True

    r2 = await client.get("/admin/v1/billing/enterprise-codes", headers=auth_headers(sa))
    assert r2.status_code == 200, r2.text
    codes = r2.json()
    assert any(c["code"] == body["code"] for c in codes)

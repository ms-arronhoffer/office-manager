"""Tracked Stripe promotion-code lifecycle tests."""
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest

from app.models.billing_usage import SubscriptionDiscountCode
from app.models.organization import Organization
from app.routers import billing as customer_billing
from app.routers.admin import billing as admin_billing
from app.services.stripe_settings import StripeSettings


def _stripe_settings() -> StripeSettings:
    return StripeSettings(
        secret_key="sk_test",
        webhook_secret="whsec_test",
        price_id_starter="",
        price_id_pro="price_base",
        price_id_starter_annual="",
        price_id_pro_annual="",
        product_id_enterprise="prod_enterprise",
    )


@pytest.mark.asyncio
async def test_create_one_use_percent_code(db_session, monkeypatch):
    async def fake_settings(db):
        return _stripe_settings()

    monkeypatch.setattr(admin_billing.stripe_cfg, "resolve_stripe_settings", fake_settings)
    monkeypatch.setattr(
        "stripe.Coupon.create",
        lambda **kwargs: SimpleNamespace(id="coupon_once", **kwargs),
    )
    monkeypatch.setattr(
        "stripe.PromotionCode.create",
        lambda **kwargs: SimpleNamespace(id="promo_once", **kwargs),
    )

    row = await admin_billing.create_discount_code(
        admin_billing.DiscountCodeCreate(
            code="welcome20",
            discount_type="percent",
            percent_off=20,
            duration="once",
            max_redemptions=1,
        ),
        db_session,
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert row.code == "WELCOME20"
    assert row.percent_off == 20
    assert row.duration == "once"
    assert row.max_redemptions == 1
    assert row.stripe_coupon_id == "coupon_once"
    assert row.stripe_promotion_code_id == "promo_once"


@pytest.mark.asyncio
async def test_redemption_is_idempotent_and_deactivates_one_use_code(db_session):
    org = Organization(name="Discount Org", slug=f"discount-{uuid.uuid4().hex}", plan="pro")
    code = SubscriptionDiscountCode(
        code="ONCE10",
        stripe_coupon_id="coupon_10",
        stripe_promotion_code_id="promo_10",
        discount_type="fixed",
        amount_off_cents=1000,
        duration="once",
        max_redemptions=1,
    )
    db_session.add_all([org, code])
    await db_session.commit()

    session = {
        "id": "cs_test_discount",
        "subscription": "sub_test",
        "discounts": [{"promotion_code": {"id": "promo_10"}}],
    }
    await customer_billing._record_discount_redemption(db_session, org, session)
    await customer_billing._record_discount_redemption(db_session, org, session)
    await db_session.refresh(code)

    assert code.times_redeemed == 1
    assert code.is_active is False


@pytest.mark.asyncio
async def test_create_fixed_term_code(db_session, monkeypatch):
    captured = {}

    async def fake_settings(db):
        return _stripe_settings()

    monkeypatch.setattr(admin_billing.stripe_cfg, "resolve_stripe_settings", fake_settings)

    def fake_coupon(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="coupon_term")

    monkeypatch.setattr("stripe.Coupon.create", fake_coupon)
    monkeypatch.setattr(
        "stripe.PromotionCode.create",
        lambda **kwargs: SimpleNamespace(id="promo_term"),
    )

    row = await admin_billing.create_discount_code(
        admin_billing.DiscountCodeCreate(
            code="SAVE25X6",
            discount_type="fixed",
            amount_off_cents=2500,
            duration="repeating",
            duration_in_months=6,
            max_redemptions=1,
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        ),
        db_session,
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert captured["amount_off"] == 2500
    assert captured["currency"] == "usd"
    assert captured["duration"] == "repeating"
    assert captured["duration_in_months"] == 6
    assert row.duration_in_months == 6

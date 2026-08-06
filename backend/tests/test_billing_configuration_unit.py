"""Fixture-free regressions for production billing configuration."""

import pytest

from app.routers.admin.billing import StripeConfigIn
from app.services.stripe_settings import validate_price_id
from app.tasks.billing_hygiene import run_billing_hygiene


def test_billing_hygiene_does_not_shadow_global_settings():
    assert "settings" not in run_billing_hygiene.__code__.co_varnames


def test_stripe_price_id_accepts_price_identifier():
    assert validate_price_id(" price_base ", "price_id_pro") == "price_base"


def test_stripe_price_id_rejects_product_identifier():
    with pytest.raises(ValueError, match="beginning with 'price_'"):
        StripeConfigIn(price_id_pro="prod_not_a_price")
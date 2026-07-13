"""Unit tests for the central entitlements catalog/resolution service.

These are pure-function tests that operate on lightweight org stubs, so they do
not require the database fixtures.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import entitlements as ent


def _org(**kwargs):
    """Build an org-like stub with sensible defaults."""
    defaults = dict(
        plan="starter",
        max_seats=None,
        entitlement_overrides={},
        is_active=True,
        payment_status="active",
        past_due_since=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── plan_entitlements ────────────────────────────────────────────────────────

def test_plan_entitlements_known_plan():
    assert ent.plan_entitlements("pro")["hvac"] is True
    assert ent.plan_entitlements("starter")["hvac"] is False


def test_plan_active_lease_limits_per_tier():
    assert ent.plan_entitlements("starter")["max_active_leases"] == 100
    assert ent.plan_entitlements("pro")["max_active_leases"] == 500
    assert ent.plan_entitlements("enterprise")["max_active_leases"] is None


def test_plan_entitlements_unknown_plan_falls_back_to_default():
    assert ent.plan_entitlements("does-not-exist") == ent.PLAN_CATALOG[ent.DEFAULT_PLAN]
    assert ent.plan_entitlements(None) == ent.PLAN_CATALOG[ent.DEFAULT_PLAN]


def test_plan_entitlements_returns_copy():
    result = ent.plan_entitlements("starter")
    result["max_offices"] = 9999
    assert ent.PLAN_CATALOG["starter"]["max_offices"] != 9999


# ── normalize_overrides ──────────────────────────────────────────────────────

def test_normalize_overrides_coerces_features_to_bool():
    assert ent.normalize_overrides({"hvac": 1})["hvac"] is True
    assert ent.normalize_overrides({"hvac": 0})["hvac"] is False


def test_normalize_overrides_accepts_none_and_nonneg_int_limits():
    out = ent.normalize_overrides({"max_offices": None, "max_seats": 25})
    assert out["max_offices"] is None
    assert out["max_seats"] == 25


def test_normalize_overrides_rejects_bool_and_negative_limits():
    out = ent.normalize_overrides({"max_offices": True, "max_seats": -3})
    assert "max_offices" not in out
    assert "max_seats" not in out


def test_normalize_overrides_drops_unknown_keys_and_non_dict():
    assert ent.normalize_overrides({"bogus": 1}) == {}
    assert ent.normalize_overrides(None) == {}
    assert ent.normalize_overrides("nope") == {}


# ── effective_entitlements ───────────────────────────────────────────────────

def test_effective_entitlements_uses_plan_defaults():
    assert ent.effective_entitlements(_org(plan="pro"))["transitions"] is True


def test_effective_entitlements_legacy_max_seats_applies():
    assert ent.effective_entitlements(_org(max_seats=7))["max_seats"] == 7


def test_effective_entitlements_overrides_win_over_plan_and_legacy():
    org = _org(plan="starter", max_seats=7, entitlement_overrides={"max_seats": 50, "hvac": True})
    resolved = ent.effective_entitlements(org)
    assert resolved["max_seats"] == 50
    assert resolved["hvac"] is True


# ── has_feature / get_limit ──────────────────────────────────────────────────

def test_has_feature_respects_override():
    assert ent.has_feature(_org(entitlement_overrides={"hvac": True}), "hvac") is True


def test_has_feature_unknown_raises():
    with pytest.raises(ValueError):
        ent.has_feature(_org(), "nope")


def test_get_limit_unknown_raises():
    with pytest.raises(ValueError):
        ent.get_limit(_org(), "nope")


# ── is_over_limit ────────────────────────────────────────────────────────────

def test_is_over_limit_unlimited_is_never_over():
    org = _org(plan="enterprise")  # max_offices unlimited
    assert ent.is_over_limit("max_offices", 10_000, org) is False


def test_is_over_limit_at_and_below_limit():
    org = _org(plan="starter")  # max_offices == 10
    assert ent.is_over_limit("max_offices", 9, org) is False
    assert ent.is_over_limit("max_offices", 10, org) is True


# ── org_access_state ─────────────────────────────────────────────────────────

def test_access_state_inactive_blocked():
    state = ent.org_access_state(_org(is_active=False))
    assert state == ent.ACCESS_BLOCKED_INACTIVE
    assert ent.is_access_blocked(state) is True


def test_access_state_canceled_blocked():
    assert ent.org_access_state(_org(payment_status="canceled")) == ent.ACCESS_BLOCKED_CANCELED


def test_access_state_past_due_within_grace():
    since = datetime.now(timezone.utc) - timedelta(days=ent.PAST_DUE_GRACE_DAYS - 1)
    state = ent.org_access_state(_org(payment_status="past_due", past_due_since=since))
    assert state == ent.ACCESS_GRACE_PAST_DUE
    assert ent.is_access_blocked(state) is False


def test_access_state_past_due_after_grace_blocked():
    since = datetime.now(timezone.utc) - timedelta(days=ent.PAST_DUE_GRACE_DAYS + 1)
    assert ent.org_access_state(_org(payment_status="past_due", past_due_since=since)) == ent.ACCESS_BLOCKED_PAST_DUE


def test_access_state_past_due_missing_since_fails_open():
    assert ent.org_access_state(_org(payment_status="past_due", past_due_since=None)) == ent.ACCESS_GRACE_PAST_DUE


def test_access_state_ok():
    state = ent.org_access_state(_org())
    assert state == ent.ACCESS_OK
    assert ent.is_access_blocked(state) is False


def test_access_denied_message_known_states():
    assert "suspended" in ent.access_denied_message(ent.ACCESS_BLOCKED_INACTIVE).lower()
    assert ent.access_denied_message("anything-else")

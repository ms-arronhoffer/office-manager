"""Central plan-entitlements catalog and per-org resolution.

This module is the single source of truth for what each subscription plan
includes. The landing page (``landing/src/components/Pricing.astro``) and the
primary application must agree with this catalog rather than hard-coding their
own copies.

Two kinds of entitlements are modelled:

* **Limits** — numeric caps. ``None`` means *unlimited*.
  - ``max_offices``: maximum number of (non-deleted) offices an org may create.
  - ``max_seats``: maximum number of active users. ``None`` = unlimited.
  - ``audit_retention_days``: how far back activity-log history is visible.
    ``None`` = unlimited retention.
* **Features** — boolean flags gating optional functionality.

Per-org overrides (stored on ``Organization.entitlement_overrides`` as JSON)
take precedence over the plan defaults, allowing a super-admin to comp a
feature, grandfather a higher office cap, or extend retention for a single org.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.organization import Organization

# Sentinel meaning "no limit".
UNLIMITED: None = None

# Limit keys (numeric, ``None`` == unlimited).
LIMIT_KEYS: tuple[str, ...] = ("max_offices", "max_seats", "audit_retention_days")

# Feature flag keys (boolean).
FEATURE_KEYS: tuple[str, ...] = (
    "hvac",
    "maintenance",
    "transitions",
    "advanced_analytics",
    "pdf_export",
    "api_access",
    "webhooks",
    "sso",
    "custom_fields",
    "ai_assist",
    "digital_waivers",
)

# All keys that may appear in an entitlement override payload.
OVERRIDE_KEYS: frozenset[str] = frozenset(LIMIT_KEYS + FEATURE_KEYS)

DEFAULT_PLAN = "starter"

# Number of days an org may remain in 'past_due' before access is locked out.
PAST_DUE_GRACE_DAYS = 10

# Per-plan default entitlements. Keep in sync with the landing-page pricing copy.
PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "starter": {
        "max_offices": 10,
        "max_seats": UNLIMITED,
        "audit_retention_days": 90,
        "hvac": False,
        "maintenance": False,
        "transitions": False,
        "advanced_analytics": False,
        "pdf_export": False,
        "api_access": False,
        "webhooks": False,
        "sso": False,
        "custom_fields": False,
        "ai_assist": False,
        "digital_waivers": False,
    },
    "pro": {
        "max_offices": 50,
        "max_seats": UNLIMITED,
        "audit_retention_days": UNLIMITED,
        "hvac": True,
        "maintenance": True,
        "transitions": True,
        "advanced_analytics": True,
        "pdf_export": True,
        "api_access": False,
        "webhooks": False,
        "sso": False,
        "custom_fields": False,
        "ai_assist": True,
        "digital_waivers": True,
    },
    "enterprise": {
        "max_offices": UNLIMITED,
        "max_seats": UNLIMITED,
        "audit_retention_days": UNLIMITED,
        "hvac": True,
        "maintenance": True,
        "transitions": True,
        "advanced_analytics": True,
        "pdf_export": True,
        "api_access": True,
        "webhooks": True,
        "sso": True,
        "custom_fields": True,
        "ai_assist": True,
        "digital_waivers": True,
    },
}


def plan_entitlements(plan: str | None) -> dict[str, Any]:
    """Return a copy of the default entitlements for ``plan``.

    Unknown or missing plans fall back to the default (starter) plan so a bad
    ``plan`` value can never silently grant more access than intended.
    """
    return dict(PLAN_CATALOG.get(plan or DEFAULT_PLAN, PLAN_CATALOG[DEFAULT_PLAN]))


def normalize_overrides(raw: Any) -> dict[str, Any]:
    """Validate and coerce a raw override mapping.

    Only recognised keys are kept. Feature flags are coerced to ``bool``; limit
    values must be ``None`` (unlimited) or a non-negative ``int``. Invalid limit
    values are dropped rather than raising, keeping resolution resilient to bad
    historical data.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in OVERRIDE_KEYS:
            continue
        if key in FEATURE_KEYS:
            cleaned[key] = bool(value)
        else:  # limit key
            if value is None:
                cleaned[key] = None
            elif isinstance(value, bool):
                # bool is a subclass of int — reject to avoid True -> 1 surprises
                continue
            elif isinstance(value, int) and value >= 0:
                cleaned[key] = value
            else:
                continue
    return cleaned


def effective_entitlements(org: "Organization") -> dict[str, Any]:
    """Resolve the effective entitlements for ``org``.

    Resolution order (later wins): plan defaults → legacy ``max_seats`` column →
    ``entitlement_overrides`` JSON.
    """
    resolved = plan_entitlements(getattr(org, "plan", None))

    # Honour the legacy per-org max_seats column when explicitly set.
    legacy_max_seats = getattr(org, "max_seats", None)
    if legacy_max_seats is not None:
        resolved["max_seats"] = legacy_max_seats

    overrides = normalize_overrides(getattr(org, "entitlement_overrides", None))
    resolved.update(overrides)
    return resolved


def has_feature(org: "Organization", feature: str) -> bool:
    """Return whether ``org`` is entitled to ``feature``."""
    if feature not in FEATURE_KEYS:
        raise ValueError(f"Unknown feature flag: {feature}")
    return bool(effective_entitlements(org).get(feature, False))


def get_limit(org: "Organization", key: str) -> int | None:
    """Return the effective numeric limit for ``key`` (``None`` == unlimited)."""
    if key not in LIMIT_KEYS:
        raise ValueError(f"Unknown limit key: {key}")
    return effective_entitlements(org).get(key)


def is_over_limit(key: str, current_count: int, org: "Organization") -> bool:
    """Return whether creating one more of ``key`` would exceed the limit."""
    limit = get_limit(org, key)
    if limit is None:
        return False
    return current_count >= limit


# ── Org access state (suspension / billing) ──────────────────────────────────

# Access decision codes returned by ``org_access_state``.
ACCESS_OK = "ok"
ACCESS_BLOCKED_INACTIVE = "blocked_inactive"
ACCESS_BLOCKED_CANCELED = "blocked_canceled"
ACCESS_BLOCKED_PAST_DUE = "blocked_past_due"
ACCESS_GRACE_PAST_DUE = "grace_past_due"
ACCESS_TRIAL_EXPIRED = "trial_expired"

_BLOCKED_STATES = frozenset(
    {ACCESS_BLOCKED_INACTIVE, ACCESS_BLOCKED_CANCELED, ACCESS_BLOCKED_PAST_DUE, ACCESS_TRIAL_EXPIRED}
)


def _is_expired_trial(org: "Organization", now: "datetime") -> bool:
    """Return True when the org's free trial has ended with no paid subscription.

    Evaluates to False when the org has a Stripe subscription (they upgraded),
    or when ``trial_ends_at`` is unset, or when the trial has not yet ended.
    """
    from datetime import timezone as _tz

    trial_ends_at = getattr(org, "trial_ends_at", None)
    if trial_ends_at is None:
        return False
    if getattr(org, "stripe_subscription_id", None) is not None:
        return False
    ts = trial_ends_at if trial_ends_at.tzinfo is not None else trial_ends_at.replace(tzinfo=_tz.utc)
    return now > ts


def org_access_state(org: "Organization", now: "datetime | None" = None) -> str:
    """Classify an org's current access state.

    * Inactive orgs are always blocked.
    * ``canceled`` billing status is blocked.
    * ``past_due`` orgs get a ``PAST_DUE_GRACE_DAYS`` grace window measured from
      ``past_due_since``; after that they are blocked. Missing ``past_due_since``
      is treated as still within grace (fail open) to avoid locking out orgs
      whose timestamp predates this feature.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    if not getattr(org, "is_active", True):
        return ACCESS_BLOCKED_INACTIVE

    payment_status = getattr(org, "payment_status", "active")
    if payment_status == "canceled":
        return ACCESS_BLOCKED_CANCELED

    # Trial expiry: org is on "active" payment status but has no paid subscription
    # and the trial window has closed.
    if payment_status == "active" and _is_expired_trial(org, now or _dt.now(_tz.utc)):
        return ACCESS_TRIAL_EXPIRED

    if payment_status == "past_due":
        since = getattr(org, "past_due_since", None)
        if since is None:
            return ACCESS_GRACE_PAST_DUE
        current = now or _dt.now(_tz.utc)
        if since.tzinfo is None:
            since = since.replace(tzinfo=_tz.utc)
        if current - since > _td(days=PAST_DUE_GRACE_DAYS):
            return ACCESS_BLOCKED_PAST_DUE
        return ACCESS_GRACE_PAST_DUE

    return ACCESS_OK


def is_access_blocked(state: str) -> bool:
    """Return whether an access-state code denotes a hard block."""
    return state in _BLOCKED_STATES


def access_denied_message(state: str) -> str:
    """Human-readable explanation for a blocked access state."""
    return {
        ACCESS_BLOCKED_INACTIVE: "This organization has been suspended. Contact support.",
        ACCESS_BLOCKED_CANCELED: "This organization's subscription has been canceled.",
        ACCESS_BLOCKED_PAST_DUE: (
            "This organization's payment is past due and the grace period has "
            "expired. Update your billing details to restore access."
        ),
        ACCESS_TRIAL_EXPIRED: (
            "Your free trial has ended. Upgrade to a paid plan to restore full access."
        ),
    }.get(state, "Access to this organization is currently restricted.")


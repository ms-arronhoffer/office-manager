"""Primary-category catalog and per-org resolution.

A *primary category* is a line of business an organisation runs — currently
``commercial`` (office/commercial leasing where the org is the lessee),
``residential`` (org-as-lessor apartment/house management), and ``self_storage``
(self-storage facility management).

This is deliberately distinct from plan *entitlements* (see
``app.services.entitlements``):

* **Entitlements** describe what a subscription *plan* allows (feature flags,
  numeric limits). They are set by billing/plan and platform overrides.
* **Categories** describe what business the *customer* actually runs. They are
  managed by the org's own admins (self-serve), with a platform (super-admin)
  override layer that always wins.

Both must be satisfied for a surface to show, but they answer different
questions and are stored/resolved separately.

Resolution
----------
Two JSON columns on :class:`~app.models.organization.Organization` back this:

* ``enabled_categories`` — a list managed by the org's admins. Defaults to
  ``["commercial", "residential"]`` to match the historical always-on
  behaviour.
* ``category_overrides`` — a ``{category: bool}`` mapping managed by platform
  super-admins that *always wins* over ``enabled_categories``.

The **effective** enabled set for an org is: start from ``enabled_categories``,
then apply each explicit ``category_overrides`` entry on top. At least one
category must remain enabled at all times.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.organization import Organization

# Canonical, ordered set of primary categories.
PRIMARY_CATEGORIES: tuple[str, ...] = ("commercial", "residential", "self_storage")

# Human-facing labels for UI/help text.
CATEGORY_LABELS: dict[str, str] = {
    "commercial": "Commercial",
    "residential": "Residential",
    "self_storage": "Self Storage",
}

# Categories enabled by default for a brand-new org (matches prior behaviour).
DEFAULT_ENABLED_CATEGORIES: tuple[str, ...] = ("commercial", "residential")


class CategoryError(ValueError):
    """Raised for invalid primary-category configuration requests."""


def is_valid_category(category: str) -> bool:
    """Return whether ``category`` is a recognised primary category."""
    return category in PRIMARY_CATEGORIES


def _require_valid(category: str) -> None:
    if not is_valid_category(category):
        raise CategoryError(f"Unknown primary category: {category!r}")


def normalize_enabled(raw: Any) -> list[str]:
    """Coerce a raw ``enabled_categories`` value into a clean, ordered list.

    Unknown values are dropped and duplicates removed. Order follows
    :data:`PRIMARY_CATEGORIES` so callers get a stable representation. An empty
    or non-list input falls back to the default enabled set so a corrupt value
    can never lock every category off.
    """
    if not isinstance(raw, (list, tuple, set)):
        return list(DEFAULT_ENABLED_CATEGORIES)
    present = {c for c in raw if c in PRIMARY_CATEGORIES}
    ordered = [c for c in PRIMARY_CATEGORIES if c in present]
    return ordered or list(DEFAULT_ENABLED_CATEGORIES)


def normalize_overrides(raw: Any) -> dict[str, bool]:
    """Coerce a raw ``category_overrides`` mapping into ``{category: bool}``.

    Only recognised category keys are kept; values are coerced to ``bool``.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, bool] = {}
    for key, value in raw.items():
        if key in PRIMARY_CATEGORIES:
            cleaned[key] = bool(value)
    return cleaned


def _apply_overrides(base: set[str], overrides: dict[str, bool]) -> list[str]:
    """Apply a ``{category: bool}`` override map on top of a base set."""
    result = set(base)
    for category, enabled in overrides.items():
        if enabled:
            result.add(category)
        else:
            result.discard(category)
    return [c for c in PRIMARY_CATEGORIES if c in result]


def _resolve_no_fallback(enabled_raw: Any, overrides_raw: Any) -> list[str]:
    """Resolve the effective set from raw values *without* the safety fallback.

    Used for write-time validation: unlike :func:`effective_enabled_categories`,
    an explicitly empty ``enabled_raw`` is honoured (not resurrected to the
    defaults) so the minimum-one-category rule can actually reject a request
    that would leave an org with no enabled categories.
    """
    base = {c for c in (enabled_raw or []) if c in PRIMARY_CATEGORIES}
    overrides = normalize_overrides(overrides_raw)
    return _apply_overrides(base, overrides)


def effective_enabled_categories(org: "Organization") -> list[str]:
    """Resolve the effective enabled categories for ``org``.

    Order: org-managed ``enabled_categories`` → platform ``category_overrides``
    (which always wins). Returns an ordered list following
    :data:`PRIMARY_CATEGORIES`.
    """
    base = set(normalize_enabled(getattr(org, "enabled_categories", None)))
    overrides = normalize_overrides(getattr(org, "category_overrides", None))
    return _apply_overrides(base, overrides)


def is_category_enabled(org: "Organization", category: str) -> bool:
    """Return whether ``category`` is effectively enabled for ``org``."""
    _require_valid(category)
    return category in effective_enabled_categories(org)


def set_category_enabled(
    org: "Organization",
    category: str,
    enabled: bool,
    *,
    as_super_admin: bool = False,
) -> list[str]:
    """Turn a primary ``category`` on or off for ``org``.

    This is the single mutation entry point for category toggling — including
    the requested ability to *turn off* a primary category (commercial,
    residential, or self storage). Toggling is non-destructive: disabling a
    category only hides its surfaces and blocks new writes; existing rows are
    retained.

    * When ``as_super_admin`` is ``False`` (org self-serve) the change is
      written to ``enabled_categories``.
    * When ``as_super_admin`` is ``True`` the change is written as an explicit
      entry in ``category_overrides``, which always wins over the org's own
      setting.

    At least one category must remain effectively enabled; attempting to
    disable the final enabled category raises :class:`CategoryError`.

    Returns the resulting effective enabled category list.
    """
    _require_valid(category)

    if as_super_admin:
        overrides = normalize_overrides(getattr(org, "category_overrides", None))
        overrides[category] = bool(enabled)
        # Super-admin overrides resolve against the org's (fallback-safe)
        # enabled list, mirroring what the runtime guard computes.
        base = set(normalize_enabled(getattr(org, "enabled_categories", None)))
        effective = _apply_overrides(base, overrides)
        if not effective:
            raise CategoryError(
                "At least one primary category must remain enabled."
            )
        org.category_overrides = overrides
    else:
        current = set(normalize_enabled(getattr(org, "enabled_categories", None)))
        if enabled:
            current.add(category)
        else:
            current.discard(category)
        new_list = [c for c in PRIMARY_CATEGORIES if c in current]
        effective = _resolve_no_fallback(
            new_list, getattr(org, "category_overrides", None)
        )
        if not effective:
            raise CategoryError(
                "At least one primary category must remain enabled."
            )
        org.enabled_categories = new_list

    return effective


def set_enabled_categories(
    org: "Organization",
    categories: list[str],
    *,
    as_super_admin: bool = False,
) -> list[str]:
    """Replace an org's org-managed enabled categories with ``categories``.

    Validates every entry, enforces the minimum-one-category rule (accounting
    for any platform overrides via the effective set), and returns the
    resulting effective enabled list. Only writes ``enabled_categories``;
    platform overrides are untouched.
    """
    for category in categories:
        _require_valid(category)
    ordered = [c for c in PRIMARY_CATEGORIES if c in set(categories)]
    effective = _resolve_no_fallback(
        ordered, getattr(org, "category_overrides", None)
    )
    if not effective:
        raise CategoryError(
            "At least one primary category must remain enabled."
        )
    org.enabled_categories = ordered
    return effective


def categories_state(org: "Organization") -> dict[str, Any]:
    """Return a serialisable snapshot of an org's category configuration."""
    return {
        "catalog": list(PRIMARY_CATEGORIES),
        "labels": dict(CATEGORY_LABELS),
        "enabled_categories": normalize_enabled(getattr(org, "enabled_categories", None)),
        "overrides": normalize_overrides(getattr(org, "category_overrides", None)),
        "effective": effective_enabled_categories(org),
    }

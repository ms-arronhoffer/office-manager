"""Tests for the primary-category catalog, resolution, toggling, and gating.

Covers both the pure-function service (``app.services.categories``) and the
HTTP surfaces that expose it: org-admin self-serve (``/organizations/me/
categories``), super-admin overrides (``/admin/v1/orgs/{id}``), and the
``require_category`` route guard applied to the Self Storage router.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.auth.password import hash_password
from app.models.customer_invoice import CustomerInvoice  # noqa: F401 - ensure mapper configured
from app.models.organization import Organization
from app.models.user import User
from app.services import categories as cat
from tests.conftest import auth_headers


def _org(**kwargs):
    defaults = dict(enabled_categories=None, category_overrides=None)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── Pure-function: normalization ─────────────────────────────────────────────

def test_primary_categories_catalog():
    assert cat.PRIMARY_CATEGORIES == ("commercial", "residential", "self_storage")


def test_normalize_enabled_orders_and_drops_unknown():
    assert cat.normalize_enabled(["self_storage", "bogus", "commercial"]) == [
        "commercial",
        "self_storage",
    ]


def test_normalize_enabled_falls_back_to_default_when_empty_or_bad():
    assert cat.normalize_enabled([]) == list(cat.DEFAULT_ENABLED_CATEGORIES)
    assert cat.normalize_enabled(None) == list(cat.DEFAULT_ENABLED_CATEGORIES)
    assert cat.normalize_enabled("nope") == list(cat.DEFAULT_ENABLED_CATEGORIES)


def test_normalize_overrides_coerces_bool_and_drops_unknown():
    assert cat.normalize_overrides({"self_storage": 1, "bogus": True}) == {
        "self_storage": True
    }
    assert cat.normalize_overrides(None) == {}


# ── Pure-function: effective resolution (overrides win) ──────────────────────

def test_effective_defaults_to_commercial_residential():
    assert cat.effective_enabled_categories(_org()) == ["commercial", "residential"]


def test_effective_override_enables_disabled_category():
    org = _org(enabled_categories=["commercial"], category_overrides={"self_storage": True})
    assert cat.effective_enabled_categories(org) == ["commercial", "self_storage"]


def test_effective_override_disables_org_enabled_category():
    org = _org(
        enabled_categories=["commercial", "residential"],
        category_overrides={"residential": False},
    )
    assert cat.effective_enabled_categories(org) == ["commercial"]
    assert cat.is_category_enabled(org, "residential") is False
    assert cat.is_category_enabled(org, "commercial") is True


# ── Pure-function: the turn-off function ─────────────────────────────────────

def test_set_category_enabled_org_scope_turns_off():
    org = _org(enabled_categories=["commercial", "residential"])
    effective = cat.set_category_enabled(org, "residential", False)
    assert effective == ["commercial"]
    assert org.enabled_categories == ["commercial"]


def test_set_category_enabled_org_scope_turns_on_self_storage():
    org = _org(enabled_categories=["commercial"])
    effective = cat.set_category_enabled(org, "self_storage", True)
    assert "self_storage" in effective
    assert org.enabled_categories == ["commercial", "self_storage"]


def test_set_category_enabled_super_admin_writes_override_and_wins():
    org = _org(enabled_categories=["commercial", "residential"])
    cat.set_category_enabled(org, "residential", False, as_super_admin=True)
    # org-managed list is untouched; the override drives the effective set.
    assert org.enabled_categories == ["commercial", "residential"]
    assert org.category_overrides == {"residential": False}
    assert cat.effective_enabled_categories(org) == ["commercial"]


def test_set_category_enabled_rejects_disabling_last_category():
    org = _org(enabled_categories=["commercial"])
    with pytest.raises(cat.CategoryError):
        cat.set_category_enabled(org, "commercial", False)


def test_set_category_enabled_rejects_unknown_category():
    with pytest.raises(cat.CategoryError):
        cat.set_category_enabled(_org(), "bogus", True)


def test_set_enabled_categories_replaces_and_enforces_min_one():
    org = _org(enabled_categories=["commercial", "residential"])
    assert cat.set_enabled_categories(org, ["self_storage"]) == ["self_storage"]
    with pytest.raises(cat.CategoryError):
        cat.set_enabled_categories(org, [])


# ── DB fixtures for HTTP tests ───────────────────────────────────────────────

async def _make_org(db_session, *, enabled=None, overrides=None, slug="acme"):
    org = Organization(
        name="Acme",
        slug=slug,
        plan="pro",
        is_active=True,
        enabled_categories=enabled,
        category_overrides=overrides,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _make_user(db_session, org, *, role="admin", email="u@acme.com", super_admin=False):
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("Pass1234!"),
        auth_provider="internal",
        role=role,
        is_active=True,
        is_super_admin=super_admin,
        organization_id=org.id if org else None,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── HTTP: require_category route guard ───────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_blocks_disabled_self_storage(client, db_session):
    org = await _make_org(db_session, enabled=["commercial", "residential"])
    user = await _make_user(db_session, org)
    resp = await client.get("/api/v1/self-storage/units", headers=auth_headers(user))
    assert resp.status_code == 403
    assert "Self Storage" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_guard_allows_enabled_self_storage(client, db_session):
    org = await _make_org(db_session, enabled=["commercial", "self_storage"])
    user = await _make_user(db_session, org)
    resp = await client.get("/api/v1/self-storage/units", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_guard_blocks_disabled_residential(client, db_session):
    org = await _make_org(db_session, enabled=["commercial"])
    user = await _make_user(db_session, org)
    resp = await client.get("/api/v1/leasing/units", headers=auth_headers(user))
    assert resp.status_code == 403


# ── HTTP: org-admin self-serve toggling ──────────────────────────────────────

@pytest.mark.asyncio
async def test_org_admin_enables_self_storage_via_put(client, db_session):
    org = await _make_org(db_session, enabled=["commercial", "residential"])
    admin = await _make_user(db_session, org)
    resp = await client.put(
        "/api/v1/organizations/me/categories",
        json={"enabled_categories": ["commercial", "self_storage"]},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["effective"]) == {"commercial", "self_storage"}

    # Now the storage router is reachable for this org.
    units = await client.get("/api/v1/self-storage/units", headers=auth_headers(admin))
    assert units.status_code == 200


@pytest.mark.asyncio
async def test_org_admin_cannot_disable_last_category(client, db_session):
    org = await _make_org(db_session, enabled=["commercial"])
    admin = await _make_user(db_session, org)
    resp = await client.put(
        "/api/v1/organizations/me/categories",
        json={"enabled_categories": []},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_non_admin_cannot_toggle_categories(client, db_session):
    org = await _make_org(db_session, enabled=["commercial", "residential"])
    viewer = await _make_user(db_session, org, role="viewer", email="v@acme.com")
    resp = await client.put(
        "/api/v1/organizations/me/categories",
        json={"enabled_categories": ["commercial"]},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 403


# ── HTTP: super-admin override always wins ───────────────────────────────────

@pytest.mark.asyncio
async def test_super_admin_override_disables_org_enabled_category(client, db_session):
    org = await _make_org(db_session, enabled=["commercial", "residential", "self_storage"])
    member = await _make_user(db_session, org, email="member@acme.com")
    super_admin = await _make_user(
        db_session, None, email="root@acme.com", super_admin=True
    )

    # Super-admin force-disables self storage for the org.
    resp = await client.patch(
        f"/admin/v1/orgs/{org.id}",
        json={"category_overrides": {"self_storage": False}},
        headers=auth_headers(super_admin),
    )
    assert resp.status_code == 200, resp.text
    assert "self_storage" not in resp.json()["categories"]["effective"]

    # Even though the org still lists it, the override wins → guard blocks.
    units = await client.get("/api/v1/self-storage/units", headers=auth_headers(member))
    assert units.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_override_rejects_disabling_all(client, db_session):
    org = await _make_org(db_session, enabled=["commercial"])
    super_admin = await _make_user(
        db_session, None, email="root2@acme.com", super_admin=True
    )
    resp = await client.patch(
        f"/admin/v1/orgs/{org.id}",
        json={"category_overrides": {"commercial": False}},
        headers=auth_headers(super_admin),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_org_admin_override_field_is_super_admin_only(client, db_session):
    org = await _make_org(db_session, enabled=["commercial", "residential"])
    # A support-console user (non super-admin) cannot set category overrides.
    support = await _make_user(db_session, None, email="support@acme.com")
    # Not a console user at all → expect a non-200 (403/404), never a silent apply.
    resp = await client.patch(
        f"/admin/v1/orgs/{org.id}",
        json={"category_overrides": {"self_storage": True}},
        headers=auth_headers(support),
    )
    assert resp.status_code >= 400
    await db_session.refresh(org)
    assert cat.normalize_overrides(org.category_overrides) == {}

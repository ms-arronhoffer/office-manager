"""Tests for owner / trust accounting (Phase 2.6)."""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

OWNERS = "/api/v1/owners"
PORTAL = "/api/v1"
GL = "/api/v1/gl"


async def _create_owner(client, user, **overrides):
    payload = {"name": "Acme Holdings", "owner_type": "company", "management_fee_percent": "10"}
    payload.update(overrides)
    resp = await client.post(f"{OWNERS}/", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── Owner CRUD ───────────────────────────────────────────────────────────────

async def test_create_and_list_owner(client, admin_user):
    owner = await _create_owner(client, admin_user)
    assert owner["name"] == "Acme Holdings"
    assert owner["owner_type"] == "company"

    listed = await client.get(f"{OWNERS}/", headers=auth_headers(admin_user))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_create_owner_rejects_bad_enum(client, admin_user):
    resp = await client.post(
        f"{OWNERS}/",
        json={"name": "X", "owner_type": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_update_and_soft_delete_owner(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    upd = await client.patch(
        f"{OWNERS}/{oid}", json={"status": "inactive"}, headers=auth_headers(admin_user)
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "inactive"

    deleted = await client.delete(f"{OWNERS}/{oid}", headers=auth_headers(admin_user))
    assert deleted.status_code == 204
    gone = await client.get(f"{OWNERS}/{oid}", headers=auth_headers(admin_user))
    assert gone.status_code == 404


async def test_viewer_cannot_create_owner(client, viewer_user):
    resp = await client.post(
        f"{OWNERS}/", json={"name": "X"}, headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


# ─── Property assignment ──────────────────────────────────────────────────────

async def test_assign_property_and_reject_duplicate(client, admin_user, sample_office):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    resp = await client.post(
        f"{OWNERS}/{oid}/properties",
        json={"office_id": str(sample_office.id), "ownership_percent": "60"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["ownership_percent"] == "60.00"

    dup = await client.post(
        f"{OWNERS}/{oid}/properties",
        json={"office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    assert dup.status_code == 400


# ─── Ledger & GL ──────────────────────────────────────────────────────────────

async def test_income_expense_fee_ledger_and_balance(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]

    async def _entry(entry_type, amount):
        r = await client.post(
            f"{OWNERS}/{oid}/ledger",
            json={"entry_type": entry_type, "amount": amount},
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 201, r.text
        return r.json()

    inc = await _entry("income", "2000.00")
    assert inc["amount"] == "2000.00"
    assert inc["journal_entry_id"] is not None

    await _entry("expense", "300.00")
    await _entry("management_fee", "200.00")

    bal = await client.get(f"{OWNERS}/{oid}/balance", headers=auth_headers(admin_user))
    assert bal.status_code == 200
    # 2000 income - 300 expense - 200 fee = 1500 owed to owner.
    assert bal.json()["balance"] == "1500.00"


async def test_income_posts_balanced_gl_entry(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "income", "amount": "1000.00"},
        headers=auth_headers(admin_user),
    )
    tb = await client.get(f"{GL}/trial-balance", headers=auth_headers(admin_user))
    assert tb.status_code == 200, tb.text
    rows = {r["code"]: r for r in tb.json()}
    # Dr Trust Cash 1050 / Cr Due to Owners 2500.
    assert rows["1050"]["balance"] == "1000.00"
    assert rows["2500"]["balance"] == "1000.00"


async def test_adjustment_allows_signed_amount_no_gl(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    r = await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "adjustment", "amount": "-50.00"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == "-50.00"
    assert r.json()["journal_entry_id"] is None
    bal = await client.get(f"{OWNERS}/{oid}/balance", headers=auth_headers(admin_user))
    assert bal.json()["balance"] == "-50.00"


async def test_ledger_rejects_zero_amount(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    r = await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "income", "amount": "0"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 400


# ─── Distributions / payouts ──────────────────────────────────────────────────

async def test_distribution_lifecycle_reduces_balance(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "income", "amount": "1000.00"},
        headers=auth_headers(admin_user),
    )
    dist = await client.post(
        f"{OWNERS}/{oid}/distributions",
        json={"amount": "400.00", "method": "ach"},
        headers=auth_headers(admin_user),
    )
    assert dist.status_code == 201, dist.text
    did = dist.json()["id"]
    assert dist.json()["status"] == "pending"

    # Pending distribution has not yet moved the balance.
    bal = await client.get(f"{OWNERS}/{oid}/balance", headers=auth_headers(admin_user))
    assert bal.json()["balance"] == "1000.00"

    paid = await client.post(
        f"{OWNERS}/{oid}/distributions/{did}/pay", headers=auth_headers(admin_user)
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["journal_entry_id"] is not None

    bal2 = await client.get(f"{OWNERS}/{oid}/balance", headers=auth_headers(admin_user))
    assert bal2.json()["balance"] == "600.00"

    # Cannot pay twice.
    again = await client.post(
        f"{OWNERS}/{oid}/distributions/{did}/pay", headers=auth_headers(admin_user)
    )
    assert again.status_code == 400


async def test_void_pending_distribution(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    dist = await client.post(
        f"{OWNERS}/{oid}/distributions",
        json={"amount": "100.00"},
        headers=auth_headers(admin_user),
    )
    did = dist.json()["id"]
    voided = await client.post(
        f"{OWNERS}/{oid}/distributions/{did}/void", headers=auth_headers(admin_user)
    )
    assert voided.status_code == 200
    assert voided.json()["status"] == "void"


# ─── Statements ───────────────────────────────────────────────────────────────

async def test_statement_opening_and_closing(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    # Prior-period income (before the statement window).
    await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "income", "amount": "500.00", "entry_date": "2026-01-15"},
        headers=auth_headers(admin_user),
    )
    # In-period income.
    await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "income", "amount": "700.00", "entry_date": "2026-02-10"},
        headers=auth_headers(admin_user),
    )
    stmt = await client.get(
        f"{OWNERS}/{oid}/statement",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28"},
        headers=auth_headers(admin_user),
    )
    assert stmt.status_code == 200, stmt.text
    body = stmt.json()
    assert body["opening_balance"] == "500.00"
    assert body["closing_balance"] == "1200.00"
    assert len(body["lines"]) == 1


# ─── Trust accounts & compliance ──────────────────────────────────────────────

async def test_trust_account_defaults_to_pending_compliance(client, admin_user):
    resp = await client.post(
        f"{OWNERS}/trust-accounts",
        json={"name": "Client Trust #1", "bank_name": "First Bank"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["compliance_status"] == "pending"
    assert resp.json()["compliance_review_required"] is True

    listed = await client.get(f"{OWNERS}/trust-accounts", headers=auth_headers(admin_user))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_trust_account_review_approves(client, admin_user):
    acct = await client.post(
        f"{OWNERS}/trust-accounts",
        json={"name": "Client Trust #2"},
        headers=auth_headers(admin_user),
    )
    aid = acct.json()["id"]
    review = await client.post(
        f"{OWNERS}/trust-accounts/{aid}/review",
        json={"compliance_status": "approved", "notes": "Reconciled"},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 200, review.text
    assert review.json()["compliance_status"] == "approved"
    assert review.json()["compliance_review_required"] is False
    assert review.json()["compliance_reviewed_at"] is not None


async def test_accountant_cannot_review_trust_account(client, accountant_user):
    acct = await client.post(
        f"{OWNERS}/trust-accounts",
        json={"name": "Client Trust #3"},
        headers=auth_headers(accountant_user),
    )
    aid = acct.json()["id"]
    review = await client.post(
        f"{OWNERS}/trust-accounts/{aid}/review",
        json={"compliance_status": "approved"},
        headers=auth_headers(accountant_user),
    )
    assert review.status_code == 403


async def test_flagged_trust_account_blocks_distribution(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    acct = await client.post(
        f"{OWNERS}/trust-accounts",
        json={"name": "Flagged Trust"},
        headers=auth_headers(admin_user),
    )
    aid = acct.json()["id"]
    await client.post(
        f"{OWNERS}/trust-accounts/{aid}/review",
        json={"compliance_status": "flagged", "notes": "Discrepancy"},
        headers=auth_headers(admin_user),
    )
    resp = await client.post(
        f"{OWNERS}/{oid}/distributions",
        json={"amount": "100.00", "trust_account_id": aid},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400
    assert "flagged" in resp.text.lower()


# ─── Owner portal ─────────────────────────────────────────────────────────────

async def _portal_token(client, admin_user, owner_id):
    invite = await client.post(
        f"{PORTAL}/owner-portal/invite",
        json={"owner_id": owner_id},
        headers=auth_headers(admin_user),
    )
    assert invite.status_code == 200, invite.text
    signup = await client.post(
        f"{PORTAL}/owner-portal/signup",
        json={"token": invite.json()["signup_token"]},
    )
    assert signup.status_code == 200, signup.text
    return signup.json()["portal_token"]


async def test_owner_portal_flow(client, admin_user):
    owner = await _create_owner(client, admin_user)
    oid = owner["id"]
    await client.post(
        f"{OWNERS}/{oid}/ledger",
        json={"entry_type": "income", "amount": "900.00"},
        headers=auth_headers(admin_user),
    )
    token = await _portal_token(client, admin_user, oid)
    hdr = {"X-Owner-Token": token}

    me = await client.get(f"{PORTAL}/owner-portal/me", headers=hdr)
    assert me.status_code == 200
    assert me.json()["name"] == "Acme Holdings"
    # Tax id must never be exposed through the portal.
    assert "tax_id" not in me.json()

    ledger = await client.get(f"{PORTAL}/owner-portal/ledger", headers=hdr)
    assert ledger.status_code == 200
    assert len(ledger.json()) == 1

    bal = await client.get(f"{PORTAL}/owner-portal/balance", headers=hdr)
    assert bal.status_code == 200
    assert bal.json()["balance"] == "900.00"


async def test_owner_portal_requires_token(client):
    resp = await client.get(f"{PORTAL}/owner-portal/me")
    assert resp.status_code == 401

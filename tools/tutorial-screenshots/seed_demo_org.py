#!/usr/bin/env python3
"""Seed a purpose-built "demo org" for the tutorial screenshot pipeline.

This script talks to a *running* backend over HTTP (it does not touch the
database directly) so every record it creates goes through the same
validation and business logic real customers hit. It is intentionally
idempotent-ish: re-running it against a fresh database is the normal case
(see the `capture` npm script), but it also tolerates re-runs against an
already-seeded database by skipping the signup step if the admin already
exists and re-using that login instead.

All data is fictional. Company/person names below are invented for this
tutorial demo and do not represent real tenants, owners, vendors or staff.

Usage:
    python seed_demo_org.py --base-url http://localhost:8000

Prints a JSON blob of credentials/ids to stdout on success; the Playwright
capture script reads this file (written to demo-org.json) to know who to log
in as and what ids to visit.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from typing import Any, Optional

import requests

DEMO_ORG_NAME = "Meridian Portfolio Group"
DEMO_PASSWORD = "TutorialDemo!2026"
DEMO_ADMIN_EMAIL = "demo.admin@meridianportfolio.example"

# Platform super-admin login, used only to raise the demo org onto the
# enterprise plan so every feature-gated screen (HVAC, transitions, digital
# waivers, client portal, API keys, webhooks...) is reachable for capture.
# Matches the DEFAULT_ADMIN_EMAIL/PASSWORD the backend bootstraps on startup.


class ApiClient:
    """Thin wrapper around `requests` that carries a bearer token."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: Optional[str] = None

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        return resp

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw).json()

    def post(self, path: str, json_body: Optional[dict] = None, **kw) -> Any:
        r = self.request("POST", path, json=json_body, **kw)
        return r.json() if r.content else None

    def patch(self, path: str, json_body: Optional[dict] = None, **kw) -> Any:
        r = self.request("PATCH", path, json=json_body, **kw)
        return r.json() if r.content else None


def _today_plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def upgrade_org_plan(base_url: str, org_id: str, platform_admin_email: str, platform_admin_password: str) -> None:
    """Log in as the platform super-admin and raise the demo org to 'enterprise'
    so every feature-gated tutorial screen is reachable for capture."""
    platform = ApiClient(base_url)
    try:
        platform.token = _login_platform_admin(platform, platform_admin_email, platform_admin_password)
    except RuntimeError as exc:
        print(f"  [plan upgrade skipped: cannot log in as platform admin] {exc}", file=sys.stderr)
        return
    try:
        platform.request("PATCH", f"/admin/v1/orgs/{org_id}", json={"plan": "enterprise"})
        print("  Upgraded demo org to the enterprise plan", file=sys.stderr)
    except RuntimeError as exc:
        print(f"  [plan upgrade failed] {exc}", file=sys.stderr)


def _login_platform_admin(platform: "ApiClient", email: str, password: str) -> str:
    """Log in as the bootstrapped platform super-admin, completing first-time
    TOTP MFA setup automatically (using pyotp) if the account requires it."""
    import pyotp

    result = platform.post("/api/v1/auth/login", {"email": email, "password": password})
    if result.get("access_token"):
        return result["access_token"]

    mfa_token = result.get("mfa_token")
    if not mfa_token:
        raise RuntimeError(f"Login for {email} returned neither a token nor an MFA challenge: {result}")

    if result.get("mfa_setup_required"):
        setup = platform.post("/api/v1/auth/mfa/setup", {"mfa_token": mfa_token})
        code = pyotp.TOTP(setup["secret"]).now()
        enabled = platform.post("/api/v1/auth/mfa/enable", {"mfa_token": mfa_token, "code": code})
        return enabled["access_token"]

    if result.get("mfa_required"):
        raise RuntimeError(
            f"{email} already has MFA enabled; the seed script cannot generate a code for an "
            "existing TOTP secret. Reset the demo database or disable MFA on this account."
        )
    raise RuntimeError(f"Unexpected login response for {email}: {result}")


def bootstrap_org(api: ApiClient) -> dict:
    """Sign up the demo org + admin. Falls back to login if it already exists."""
    try:
        result = api.post(
            "/api/v1/organizations/signup",
            {
                "org_name": DEMO_ORG_NAME,
                "email": DEMO_ADMIN_EMAIL,
                "password": DEMO_PASSWORD,
                "display_name": "Ava Whitfield",
            },
        )
        api.token = result["access_token"]
        print(f"  Created demo org {DEMO_ORG_NAME!r}", file=sys.stderr)
    except RuntimeError as exc:
        if "409" not in str(exc):
            raise
        print("  Demo org already exists, logging in instead", file=sys.stderr)
        result = api.post("/api/v1/auth/login", {"email": DEMO_ADMIN_EMAIL, "password": DEMO_PASSWORD})
        api.token = result["access_token"]
    return result


def create_internal_users(api: ApiClient) -> dict:
    """Create one user per internal role so each has a stable, known login."""
    users = {
        "editor": ("Marcus Delgado", "demo.editor@meridianportfolio.example", "editor"),
        "accountant": ("Priya Raman", "demo.accountant@meridianportfolio.example", "accountant"),
        "viewer": ("Sam Okafor", "demo.viewer@meridianportfolio.example", "viewer"),
    }
    created = {}
    existing = {u["email"]: u for u in api.get("/api/v1/users")["items"]}
    for key, (display_name, email, role) in users.items():
        if email in existing:
            created[key] = {"email": email, "password": DEMO_PASSWORD, "role": role}
            continue
        api.post(
            "/api/v1/users",
            {
                "email": email,
                "display_name": display_name,
                "password": DEMO_PASSWORD,
                "role": role,
            },
        )
        created[key] = {"email": email, "password": DEMO_PASSWORD, "role": role}
    return created


def seed_offices(api: ApiClient) -> list[dict]:
    offices = [
        dict(office_number=101, region_number=1, location_type="Branch Office", location_name="Harbor View Tower",
             address_line_1="480 Harbor View Blvd", city="Portland", state="OR", zip_code="97201",
             total_sqft=42000, usable_sqft=39000, headcount_capacity=180, current_headcount=142, is_active=True),
        dict(office_number=102, region_number=1, location_type="Branch Office", location_name="Cedar Ridge Commons",
             address_line_1="12 Cedar Ridge Way", city="Bellevue", state="WA", zip_code="98004",
             total_sqft=28500, usable_sqft=26000, headcount_capacity=110, current_headcount=97, is_active=True),
        dict(office_number=103, region_number=2, location_type="Regional HQ", location_name="Meridian Plaza",
             address_line_1="900 Meridian Plaza Dr", city="Austin", state="TX", zip_code="78701",
             total_sqft=61000, usable_sqft=57500, headcount_capacity=260, current_headcount=231, is_active=True),
    ]
    created = []
    for o in offices:
        created.append(api.post("/api/v1/offices", o))
    return created


def seed_landlords(api: ApiClient) -> list[dict]:
    landlords = [
        dict(office_name="Harborline Realty Partners", landlord_name="Harborline Realty Partners LLC",
             contact_name="Denise Farrow", contact_email="denise.farrow@harborline.example", contact_phone="503-555-0134"),
        dict(office_name="Cascade Property Trust", landlord_name="Cascade Property Trust",
             contact_name="Ian Mackey", contact_email="ian.mackey@cascadetrust.example", contact_phone="425-555-0166"),
    ]
    created = []
    for entry in landlords:
        created.append(api.post("/api/v1/landlords", entry))
    return created


def seed_vendors(api: ApiClient) -> list[dict]:
    vendors = [
        dict(company_name="Summit Facilities Services", services="Janitorial, groundskeeping",
             contact_name="Renee Ortiz", contact_email="renee@summitfacilities.example", contact_phone="512-555-0110",
             is_preferred=True),
        dict(company_name="Bluepeak HVAC & Mechanical", services="HVAC install and repair",
             contact_name="Curtis Boyle", contact_email="curtis@bluepeakhvac.example", contact_phone="503-555-0198",
             is_1099_vendor=True, legal_name="Bluepeak Mechanical Inc."),
        dict(company_name="Ironclad Security Systems", services="Access control, alarm monitoring",
             contact_name="Tanya Wu", contact_email="tanya@ironcladsecurity.example", contact_phone="425-555-0142"),
    ]
    created = []
    for v in vendors:
        created.append(api.post("/api/v1/vendors", v))
    return created


def seed_leases(api: ApiClient, offices: list[dict], landlords: list[dict]) -> list[dict]:
    exp_1 = date.today() + timedelta(days=300)
    exp_2 = date.today() + timedelta(days=60)
    exp_3 = date.today() + timedelta(days=2000)
    leases = [
        dict(office_id=offices[0]["id"], lease_name="Harbor View Tower - Suite 400", tenant_name="Northgate Analytics Inc.",
             landlord_id=landlords[0]["id"], commencement_date=_today_plus(-540), lease_expiration=exp_1.isoformat(),
             expiration_year=exp_1.year, base_rent=48500, status="active", lease_classification="operating"),
        dict(office_id=offices[1]["id"], lease_name="Cedar Ridge Commons - Floor 2", tenant_name="Northgate Analytics Inc.",
             landlord_id=landlords[1]["id"], commencement_date=_today_plus(-1200), lease_expiration=exp_2.isoformat(),
             expiration_year=exp_2.year, base_rent=31200, status="active", lease_classification="operating"),
        dict(office_id=offices[2]["id"], lease_name="Meridian Plaza - Full Floor 12", tenant_name="Northgate Analytics Inc.",
             landlord_id=landlords[0]["id"], commencement_date=_today_plus(-90), lease_expiration=exp_3.isoformat(),
             expiration_year=exp_3.year, base_rent=88900, status="pending", lease_classification="operating"),
    ]
    created = []
    for entry in leases:
        try:
            created.append(api.post("/api/v1/leases", entry))
        except RuntimeError as exc:
            print(f"  [lease skipped] {exc}", file=sys.stderr)
    return created


def seed_maintenance(api: ApiClient, offices: list[dict], vendors: list[dict]) -> None:
    try:
        cat = api.post("/api/v1/ticket-categories", {"name": "HVAC"})
        cat_id = cat["id"]
    except RuntimeError:
        cats = api.get("/api/v1/ticket-categories")
        cat_id = cats[0]["id"] if cats else None
    tickets = [
        dict(office_id=offices[0]["id"], category_id=cat_id, subject="Rooftop unit short-cycling",
             description="RTU-3 on the east roof is short-cycling during peak afternoon load.",
             priority="high", status="in_progress", vendor_id=vendors[1]["id"]),
        dict(office_id=offices[1]["id"], category_id=cat_id, subject="Lobby thermostat unresponsive",
             description="Front lobby thermostat display is blank; suspect a wiring fault.",
             priority="medium", status="open"),
    ]
    for t in tickets:
        try:
            api.post("/api/v1/maintenance-tickets", t)
        except RuntimeError as exc:
            print(f"  [ticket skipped] {exc}", file=sys.stderr)


def seed_hvac_contracts(api: ApiClient, offices: list[dict], vendors: list[dict]) -> None:
    try:
        api.post("/api/v1/hvac-contracts", {
            "office_id": offices[0]["id"], "hvac_company": vendors[1]["company_name"],
            "contact": "Curtis Boyle", "frequency": "Quarterly", "next_service": "Q1 2027",
        })
    except RuntimeError as exc:
        print(f"  [hvac contract skipped] {exc}", file=sys.stderr)


def seed_transitions(api: ApiClient, offices: list[dict]) -> None:
    try:
        api.post("/api/v1/transitions", {
            "office_id": offices[2]["id"], "transition_type": "new_office",
            "status": "in_progress", "target_date": _today_plus(45),
        })
    except RuntimeError as exc:
        print(f"  [transition skipped] {exc}", file=sys.stderr)


def seed_insurance_certificates(api: ApiClient, vendors: list[dict]) -> None:
    try:
        api.post("/api/v1/insurance-certificates", {
            "vendor_id": vendors[0]["id"],
            "certificate_type": "general_liability", "insurer": "Pinegate Mutual Insurance",
            "policy_number": "PGM-88213-A", "effective_date": _today_plus(-120),
            "expiration_date": _today_plus(245), "certificate_holder": DEMO_ORG_NAME,
        })
    except RuntimeError as exc:
        print(f"  [insurance cert skipped] {exc}", file=sys.stderr)


def seed_residential(api: ApiClient, offices: list[dict]) -> dict:
    result: dict = {}
    unit = api.post("/api/v1/leasing/units", {
        "office_id": offices[0]["id"], "unit_number": "4B", "name": "Harbor View 4B",
        "bedrooms": 2, "bathrooms": 2, "square_feet": 1080, "market_rent": 2450, "status": "occupied",
    })
    result["unit"] = unit
    resident = api.post("/api/v1/leasing/residents", {
        "first_name": "Elena", "last_name": "Vasquez", "email": "elena.vasquez@residentmail.example",
        "phone": "503-555-0177", "status": "current",
    })
    result["resident"] = resident
    lease = api.post("/api/v1/leasing/leases", {
        "unit_id": unit["id"], "name": "Elena Vasquez - Unit 4B", "status": "active",
        "start_date": _today_plus(-200), "end_date": _today_plus(165),
        "rent_amount": 2450, "security_deposit": 2450,
        "occupants": [{"resident_id": resident["id"], "role": "primary", "is_primary": True}],
    })
    result["lease"] = lease
    vacant_unit = api.post("/api/v1/leasing/units", {
        "office_id": offices[0]["id"], "unit_number": "2A", "name": "Harbor View 2A",
        "bedrooms": 1, "bathrooms": 1, "square_feet": 720, "market_rent": 1850, "status": "available",
    })
    result["vacant_unit"] = vacant_unit
    try:
        result["listing"] = api.post("/api/v1/listings", {
            "unit_id": vacant_unit["id"], "title": "Bright 1BR at Harbor View — available now",
            "headline": "Sunny one-bedroom with harbor glimpses",
            "marketing_rent": 1850, "bedrooms": 1, "bathrooms": 1, "square_feet": 720,
        })
    except RuntimeError as exc:
        print(f"  [listing skipped] {exc}", file=sys.stderr)
    try:
        result["announcement"] = api.post("/api/v1/announcements", {
            "title": "Scheduled water shutoff — Thursday 9am-12pm",
            "body": "Maintenance will briefly shut off water building-wide for valve replacement.",
            "channels": ["portal"],
        })
    except RuntimeError as exc:
        print(f"  [announcement skipped] {exc}", file=sys.stderr)
    return result


def seed_owner(api: ApiClient, offices: list[dict]) -> dict:
    owner = api.post("/api/v1/owners", {
        "owner_type": "company", "name": "Northgate Capital Partners",
        "email": "owner.contact@northgatecapital.example", "phone": "512-555-0155",
        "management_fee_percent": 8,
    })
    try:
        api.post(f"/api/v1/owners/{owner['id']}/properties", {
            "office_id": offices[2]["id"], "ownership_percent": 100, "management_fee_percent": 8,
        })
    except RuntimeError as exc:
        print(f"  [owner property skipped] {exc}", file=sys.stderr)
    return owner


def seed_waiver_template(api: ApiClient) -> Optional[dict]:
    try:
        return api.post("/api/v1/waivers/templates", {
            "name": "Facility Visitor Liability Waiver",
            "description": "Standard liability waiver for guests and contractors on-site.",
            "body": "I acknowledge and accept the visitor safety terms for this facility.",
        })
    except RuntimeError as exc:
        print(f"  [waiver template skipped] {exc}", file=sys.stderr)
        return None


def mint_resident_invite(api: ApiClient, resident_id: str) -> dict:
    return api.post("/api/v1/resident-portal/invite", {"resident_id": resident_id})


def mint_owner_invite(api: ApiClient, owner_id: str) -> dict:
    return api.post("/api/v1/owner-portal/invite", {"owner_id": owner_id})


def mint_vendor_token(api: ApiClient, vendor_id: str) -> dict:
    return api.post(f"/api/v1/vendors/{vendor_id}/portal-token", {})


def mint_client_invite(api: ApiClient, entity_type: str, entity_id: str) -> dict:
    return api.post("/api/v1/client-portal/invite", {"entity_type": entity_type, "entity_id": entity_id})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--out", default="demo-org.json")
    parser.add_argument("--platform-admin-email", default="admin@officemanager.local",
                         help="Platform super-admin login, used to raise the demo org onto the enterprise plan.")
    parser.add_argument("--platform-admin-password", default=None)
    args = parser.parse_args()

    api = ApiClient(args.base_url)
    print("Bootstrapping demo organization...", file=sys.stderr)
    signup_result = bootstrap_org(api)

    if args.platform_admin_password:
        org_id = signup_result.get("organization", {}).get("id")
        if org_id:
            upgrade_org_plan(args.base_url, org_id, args.platform_admin_email, args.platform_admin_password)
        else:
            # Signup was skipped (org already existed); look the org up as the platform admin instead.
            platform = ApiClient(args.base_url)
            try:
                platform.token = _login_platform_admin(platform, args.platform_admin_email, args.platform_admin_password)
                orgs = platform.get("/admin/v1/orgs", params={"search": DEMO_ORG_NAME})
                items = orgs.get("items", [])
                if items:
                    upgrade_org_plan(args.base_url, items[0]["id"], args.platform_admin_email, args.platform_admin_password)
            except RuntimeError as exc:
                print(f"  [plan upgrade lookup skipped] {exc}", file=sys.stderr)

    print("Creating internal role users...", file=sys.stderr)
    internal_users = create_internal_users(api)

    print("Seeding offices...", file=sys.stderr)
    offices = seed_offices(api)

    print("Seeding landlords...", file=sys.stderr)
    landlords = seed_landlords(api)

    print("Seeding vendors...", file=sys.stderr)
    vendors = seed_vendors(api)

    print("Seeding leases...", file=sys.stderr)
    leases = seed_leases(api, offices, landlords)

    print("Seeding maintenance tickets...", file=sys.stderr)
    seed_maintenance(api, offices, vendors)

    print("Seeding HVAC contracts...", file=sys.stderr)
    seed_hvac_contracts(api, offices, vendors)

    print("Seeding transitions...", file=sys.stderr)
    seed_transitions(api, offices)

    print("Seeding insurance certificates...", file=sys.stderr)
    seed_insurance_certificates(api, vendors)

    print("Seeding residential (units/residents/leases/listings)...", file=sys.stderr)
    residential = seed_residential(api, offices)

    print("Seeding owner + trust accounting...", file=sys.stderr)
    owner = seed_owner(api, offices)

    print("Seeding waiver template...", file=sys.stderr)
    waiver_template = seed_waiver_template(api)

    portal_credentials: dict = {}

    print("Minting resident portal invite...", file=sys.stderr)
    try:
        invite = mint_resident_invite(api, residential["resident"]["id"])
        portal_credentials["resident"] = {"invite_token": invite.get("signup_token"), "email": "elena.vasquez@residentmail.example"}
    except RuntimeError as exc:
        print(f"  [resident invite skipped] {exc}", file=sys.stderr)

    print("Minting owner portal invite...", file=sys.stderr)
    try:
        invite = mint_owner_invite(api, owner["id"])
        portal_credentials["owner"] = {"invite_token": invite.get("signup_token"), "email": "owner.contact@northgatecapital.example"}
    except RuntimeError as exc:
        print(f"  [owner invite skipped] {exc}", file=sys.stderr)

    print("Minting vendor portal token...", file=sys.stderr)
    try:
        token = mint_vendor_token(api, vendors[1]["id"])
        portal_credentials["vendor"] = {"token": token.get("token")}
    except RuntimeError as exc:
        print(f"  [vendor token skipped] {exc}", file=sys.stderr)

    print("Minting client portal invite...", file=sys.stderr)
    try:
        invite = mint_client_invite(api, "landlord", landlords[0]["id"])
        portal_credentials["client"] = {"invite_token": invite.get("signup_token")}
    except RuntimeError as exc:
        print(f"  [client invite skipped] {exc}", file=sys.stderr)

    output = {
        "org_name": DEMO_ORG_NAME,
        "admin": {"email": DEMO_ADMIN_EMAIL, "password": DEMO_PASSWORD},
        "internal_users": internal_users,
        "offices": offices,
        "residential": {k: v for k, v in residential.items() if v},
        "leases": leases,
        "owner": owner,
        "waiver_template": waiver_template,
        "portal_credentials": portal_credentials,
    }
    with open(args.out, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Demo org ready. Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

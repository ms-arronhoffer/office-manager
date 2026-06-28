"""
run_seed.py - Orchestrator for all seed/import scripts.

Run from the backend directory:
    python -m seed.run_seed
or:
    python seed/run_seed.py

Seed only the default organization (creates the default org + admin user +
email reminder rules + ticket categories, skipping the spreadsheet imports):
    python -m seed.run_seed --bootstrap-only

Required env vars:
    DATABASE_URL_SYNC      - synchronous postgres URL
    DEFAULT_ADMIN_EMAIL    - (optional) defaults to admin@officemanager.local
    DEFAULT_ADMIN_PASSWORD - (optional) defaults to changeme123
"""

import argparse
import os
import sys
import uuid
from pathlib import Path

# Default organization every seeded record is attached to. Matches the UUID
# created by ``backend/start.py`` and Alembic migration 023 so the default admin
# (whose ``organization_id`` is the same value) can actually see the data — the
# API routers all filter by ``current_user.organization_id``, so records left
# with a NULL ``organization_id`` are invisible in the app ("no data").
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# ---------------------------------------------------------------------------
# Path setup — must happen before any app/seed imports
# ---------------------------------------------------------------------------
_seed_dir = Path(__file__).parent
_backend_dir = _seed_dir.parent
for _p in (str(_backend_dir), str(_seed_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------
from sqlalchemy import create_engine                            # noqa: E402
from sqlalchemy.orm import Session                              # noqa: E402

from app.models import Base, User, EmailReminderRule            # noqa: E402
from app.models.organization import Organization               # noqa: E402
from app.models.maintenance_ticket import TicketCategory        # noqa: E402
from app.auth.password import hash_password                     # noqa: E402

from seed.import_offices import import_offices                  # noqa: E402
from seed.import_leases import import_leases                    # noqa: E402
from seed.import_landlords import import_landlords              # noqa: E402
from seed.import_transitions import import_transitions          # noqa: E402
from seed.import_hq_hvac import import_hq_hvac                  # noqa: E402
from seed.import_hvac_contracts import import_hvac_contracts    # noqa: E402
from seed.import_vendors import import_vendors                  # noqa: E402
from seed.import_maintenance_tickets import import_maintenance_tickets  # noqa: E402


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def _ensure_default_org(session: Session) -> None:
    """Ensure the default organization exists so seeded records can attach to it."""
    existing = session.get(Organization, DEFAULT_ORG_ID)
    if existing:
        print(f"  Default organization already exists: {existing.name}")
        return
    org = Organization(
        id=DEFAULT_ORG_ID,
        name="Default Organization",
        slug="default",
        plan="starter",
        is_active=True,
        onboarding_complete=True,
    )
    session.add(org)
    session.flush()
    print("  Created default organization")


def _create_default_admin(session: Session, admin_email: str, admin_password: str) -> None:
    existing = session.query(User).filter_by(email=admin_email).first()
    if existing:
        # Heal an admin that predates org-scoped seeding so it can see the data.
        if existing.organization_id != DEFAULT_ORG_ID:
            existing.organization_id = DEFAULT_ORG_ID
        if not existing.is_super_admin:
            existing.is_super_admin = True
        print(f"  Admin user already exists: {admin_email}")
        return
    admin = User(
        email=admin_email,
        display_name="Admin",
        password_hash=hash_password(admin_password),
        auth_provider="internal",
        role="admin",
        is_active=True,
        is_super_admin=True,
        organization_id=DEFAULT_ORG_ID,
    )
    session.add(admin)
    session.flush()
    print(f"  Created admin user: {admin_email}")


def _create_email_reminder_rules(session: Session, admin_email: str) -> None:
    existing_count = session.query(EmailReminderRule).count()
    if existing_count > 0:
        print(f"  Email reminder rules already exist ({existing_count}), skipping")
        return

    default_rules = [
        ("Lease Expiration - 180 Days",  "lease_expiration", 180),
        ("Lease Expiration - 90 Days",   "lease_expiration",  90),
        ("Lease Expiration - 60 Days",   "lease_expiration",  60),
        ("Lease Expiration - 30 Days",   "lease_expiration",  30),
        ("Lease Notice Date - 30 Days",  "lease_notice_date", 30),
        ("Lease Notice Date - 14 Days",  "lease_notice_date", 14),
        ("HVAC Service Due - 30 Days",   "hvac_service",      30),
        ("HQ PM Task Due - 14 Days",     "hq_pm",             14),
    ]

    created = 0
    for rule_name, rule_type, days in default_rules:
        rule = EmailReminderRule(
            rule_name=rule_name,
            rule_type=rule_type,
            days_before=days,
            recipient_emails=[admin_email],
            is_active=True,
        )
        session.add(rule)
        created += 1

    session.flush()
    print(f"  Created {created} email reminder rules")


def _create_ticket_categories(session: Session) -> None:
    existing_count = session.query(TicketCategory).count()
    if existing_count > 0:
        print(f"  Ticket categories already exist ({existing_count}), skipping")
        return

    default_categories = [
        "Electrical",
        "Plumbing",
        "HVAC",
        "Cleaning",
        "Shredding",
        "Pest Control",
        "Elevator",
        "Fire/Safety",
        "General Repair",
        "Other",
    ]

    created = 0
    for name in default_categories:
        session.add(TicketCategory(name=name))
        created += 1

    session.flush()
    print(f"  Created {created} ticket categories")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_seed(bootstrap_only: bool = False) -> None:
    from app.config import settings
    db_url = settings.DATABASE_URL_SYNC
    admin_email = settings.DEFAULT_ADMIN_EMAIL
    admin_password = settings.DEFAULT_ADMIN_PASSWORD

    print(f"\n=== SwiftLease Data Import ===")
    print(f"Database: {db_url.split('@')[-1]}")  # hide credentials
    if bootstrap_only:
        print("Mode: bootstrap-only (default organization, admin, rules, categories)")

    engine = create_engine(db_url, echo=False)

    # Schema setup is owned by `start.py` (Alembic). The seed script only
    # loads data into existing tables. Calling `Base.metadata.create_all()`
    # here clashes with the already-created schema and raises
    # "duplicate key on pg_type_typname_nsp_index" on Postgres.
    #
    # Fail fast with a clear message if the schema isn't ready yet so the
    # operator doesn't have to chase a deep SQLAlchemy traceback.
    from sqlalchemy import inspect as _sa_inspect
    insp = _sa_inspect(engine)
    required_tables = ("managers", "offices", "users", "vendors")
    missing = [t for t in required_tables if not insp.has_table(t)]
    if missing:
        raise SystemExit(
            f"Required tables missing: {missing}. "
            "Schema setup did not complete on the backend container. "
            "Check `docker compose logs backend` for `[start]` lines that report "
            "what create_all / alembic upgrade did, and re-run `docker compose up -d` "
            "before running the seed."
        )

    with Session(engine) as session:

        # 0 ── Ensure the default organization exists so every seeded record can
        # be attached to it (the API filters all data by organization_id).
        step = "1/2" if bootstrap_only else "1/10"
        print(f"\n[{step}] Ensuring default organization...")
        _ensure_default_org(session)
        session.commit()

        if bootstrap_only:
            # Bootstrap-only: skip the spreadsheet imports and just create the
            # admin user, email reminder rules, and ticket categories so the
            # default organization is usable out of the box.
            print("\n[2/2] Creating default admin user, email reminder rules, and ticket categories...")
            _create_default_admin(session, admin_email, admin_password)
            _create_email_reminder_rules(session, admin_email)
            _create_ticket_categories(session)
            session.commit()
            print("  Done")
            print("\n=== Bootstrap Complete ===\n")
            return

        # 1 ── Offices + managers (must be first; all other importers depend on maps)
        print("\n[2/10] Importing offices and managers...")
        manager_map, office_map = import_offices(session, DEFAULT_ORG_ID)
        session.commit()
        print(f"  Done: {len(manager_map)} managers, {len(office_map)} offices")

        # 2 ── Leases (depends on manager_map + office_map)
        print("\n[3/10] Importing leases...")
        import_leases(session, manager_map, office_map, DEFAULT_ORG_ID)
        session.commit()
        print("  Done")

        # 3 ── Landlords (depends on office_map)
        print("\n[4/10] Importing landlords...")
        import_landlords(session, office_map, DEFAULT_ORG_ID)
        session.commit()
        print("  Done")

        # 4 ── Office transitions (depends on office_map)
        print("\n[5/10] Importing office transitions...")
        import_transitions(session, office_map, DEFAULT_ORG_ID)
        session.commit()
        print("  Done")

        # 5 ── HQ HVAC (no FK dependencies)
        print("\n[6/10] Importing HQ HVAC system data...")
        import_hq_hvac(session)
        session.commit()
        print("  Done")

        # 6 ── HVAC contracts (depends on manager_map + office_map)
        print("\n[7/10] Importing HVAC contracts...")
        import_hvac_contracts(session, manager_map, office_map, DEFAULT_ORG_ID)
        session.commit()
        print("  Done")

        # 7 ── Vendors (depends on office_map for vendor-office links)
        print("\n[8/10] Importing vendors...")
        import_vendors(session, office_map, DEFAULT_ORG_ID)
        session.commit()
        print("  Done")

        # 8 ── Bootstrap: admin user, email reminder rules, ticket categories
        #      (must run before maintenance tickets, which need a creating user
        #      and the ticket categories to exist).
        print("\n[9/10] Creating default admin user, email reminder rules, and ticket categories...")
        _create_default_admin(session, admin_email, admin_password)
        _create_email_reminder_rules(session, admin_email)
        _create_ticket_categories(session)
        session.commit()
        print("  Done")

        # 9 ── Maintenance tickets (depends on offices, categories, vendors,
        #      managers, and the admin user created above)
        print("\n[10/10] Importing maintenance tickets...")
        import_maintenance_tickets(session, office_map, DEFAULT_ORG_ID)
        session.commit()
        print("  Done")

    print("\n=== Import Complete ===\n")


# Allow both `python run_seed.py` and `python -m seed.run_seed`
main = run_seed

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed SwiftLease data, or just the default organization.",
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Only create the default organization, admin user, email reminder "
             "rules, and ticket categories; skip the spreadsheet imports.",
    )
    args = parser.parse_args()
    run_seed(bootstrap_only=args.bootstrap_only)

"""Startup script: run migrations, ensure admin user, then launch uvicorn."""
import os
import subprocess
import sys
import uuid

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import sync_engine
from app.models import Base, User  # noqa: F401 - registers all models
from app.models.organization import Organization
from app.auth.password import hash_password

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _run_alembic(*args: str) -> None:
    """Invoke the Alembic CLI from the backend root, passing the live DB URL."""
    env = os.environ.copy()
    env["DATABASE_URL_SYNC"] = settings.DATABASE_URL_SYNC
    cmd = ["alembic", *args]
    print(f"[start] $ {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        sys.exit(f"[start] alembic command failed: {' '.join(cmd)}")


def _initialize_schema() -> None:
    """
    Make sure the database schema is current.

    Two cases must be handled:

    1. **Fresh database** (no `alembic_version` table). The app has historically
       initialized via `Base.metadata.create_all()`, which builds every table
       from the current ORM models. After that, we *stamp* Alembic at the
       latest revision so future deployments only run new migrations.

    2. **Existing database** (already has `alembic_version`, or has tables
       from a prior `create_all`-only deployment). We run
       `alembic upgrade head` to apply any pending migrations.

       For case 2 sub-case "existing tables but no alembic_version row"
       (i.e. the very first time the app is upgraded after Alembic was
       wired in), we stamp at the *baseline* revision (the most recent
       migration the live schema is known to satisfy) before upgrading.
       Today every release before 007 was applied via `create_all`, so we
       stamp at 006 and let 007+ run.
    """
    inspector = inspect(sync_engine)
    has_alembic_table = inspector.has_table("alembic_version")
    has_app_tables = inspector.has_table("vendors") or inspector.has_table("offices")

    print(
        f"[start] Schema state: alembic_version={has_alembic_table}, "
        f"app_tables={has_app_tables}"
    )

    if not has_app_tables:
        # Brand-new database. Build everything from the current models, then
        # stamp Alembic so it knows we're already at head.
        print("[start] Fresh database detected — creating tables from models...")
        # Sanity-check the metadata actually has the models registered. If
        # this is empty something went very wrong with imports.
        registered = sorted(Base.metadata.tables.keys())
        print(f"[start] {len(registered)} tables registered in Base.metadata: {registered}")
        if not registered:
            sys.exit("[start] No tables registered in Base.metadata — model imports are broken.")

        Base.metadata.create_all(bind=sync_engine)

        # Verify the tables actually landed in the database.
        post_inspector = inspect(sync_engine)
        actual = sorted(post_inspector.get_table_names())
        print(f"[start] {len(actual)} tables now present in database: {actual}")
        missing = set(registered) - set(actual)
        if missing:
            sys.exit(f"[start] create_all did not create these tables: {sorted(missing)}")

        print("[start] Tables created. Stamping alembic at head...")
        _run_alembic("stamp", "head")
        return

    if not has_alembic_table:
        # Pre-Alembic deployment. Tables exist but Alembic was never tracked.
        # Mark the schema as being at the last "create_all-only" revision (006)
        # so subsequent migrations (007+) apply cleanly.
        print(
            "[start] Existing tables found but no alembic_version table; "
            "stamping at baseline revision 006 before upgrading."
        )
        _run_alembic("stamp", "006")

    print("[start] Running alembic upgrade head...")
    _run_alembic("upgrade", "head")

    # Sanity-check after upgrade: a couple of must-have tables.
    post_inspector = inspect(sync_engine)
    for required in ("managers", "offices", "users", "vendors"):
        if not post_inspector.has_table(required):
            sys.exit(f"[start] Required table '{required}' is missing after schema initialization.")
    print("[start] Schema verification passed.")


def _ensure_default_admin() -> None:
    """Create the default admin user on first boot so the app is immediately usable."""
    with Session(sync_engine) as session:
        existing = session.query(User).filter_by(email=settings.DEFAULT_ADMIN_EMAIL).first()
        if existing:
            print(f"[start] Admin user already exists: {settings.DEFAULT_ADMIN_EMAIL}")
            return
        admin = User(
            email=settings.DEFAULT_ADMIN_EMAIL,
            display_name="Admin",
            password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
            auth_provider="internal",
            role="admin",
            is_active=True,
            organization_id=DEFAULT_ORG_ID,
        )
        session.add(admin)
        session.commit()
        print(f"[start] Created default admin user: {settings.DEFAULT_ADMIN_EMAIL}")


def _ensure_default_org() -> None:
    """Ensure the default organization exists (idempotent)."""
    with Session(sync_engine) as session:
        existing = session.get(Organization, DEFAULT_ORG_ID)
        if existing:
            print(f"[start] Default organization already exists: {existing.name}")
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
        session.commit()
        print("[start] Created default organization.")


_initialize_schema()
_ensure_default_org()
_ensure_default_admin()


def _ensure_raw_tables() -> None:
    """
    Create tables that are managed by raw SQL (no ORM model) and therefore
    not created by Base.metadata.create_all() on fresh-database deployments.
    Safe to run on every startup — all statements use CREATE TABLE IF NOT EXISTS.
    """
    statements = [
        # Persistent auth rate-limiting (migration 020)
        """
        CREATE TABLE IF NOT EXISTS auth_lockouts (
            email        VARCHAR(255) PRIMARY KEY,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]
    with sync_engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()
    print("[start] Raw-SQL tables verified.")


_ensure_raw_tables()

# Hand off to uvicorn.
sys.exit(subprocess.call([
    "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
]))


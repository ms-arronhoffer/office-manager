"""Startup script: run migrations, ensure admin user, then launch uvicorn."""
import os
import subprocess
import sys
import traceback
import uuid

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import sync_engine
from app.models import Base, User  # noqa: F401 - registers all models
from app.models.organization import Organization
from app.auth.password import hash_password

DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Full-text search artifacts that live in Alembic migration 018 but are NOT
# represented on the ORM models, so ``Base.metadata.create_all`` never builds
# them. The ``to_tsvector`` columns below are required by several create/update
# endpoints (e.g. update_search_vector). On a fresh database we create the
# schema via ``create_all`` and then ``alembic stamp head`` — which marks 018 as
# applied without running it — so these must be created explicitly first, or
# the columns are silently absent and writes that touch them 500. Keyed by
# table, each value is the ``to_tsvector`` body used to populate the column.
_SEARCH_VECTOR_SOURCES = {
    "offices": "coalesce(location_name,'') || ' ' || coalesce(city,'') || ' ' || coalesce(notes,'')",
    "leases": "coalesce(lease_name,'') || ' ' || coalesce(lessor_name,'')",
    "maintenance_tickets": "coalesce(subject,'') || ' ' || coalesce(description,'')",
    "landlords": "coalesce(landlord_company,'') || ' ' || coalesce(contact_name,'')",
}

# GIN index names mirror migration 018 so a later ``alembic upgrade`` is a no-op.
_SEARCH_VECTOR_INDEXES = {
    "offices": "idx_offices_fts",
    "leases": "idx_leases_fts",
    "maintenance_tickets": "idx_tickets_fts",
    "landlords": "idx_landlords_fts",
}


def _ensure_search_vector_columns() -> None:
    """Create the full-text ``search_vector`` columns/indexes idempotently.

    Mirrors Alembic migration 018. Called on the fresh-database path after
    ``create_all`` and before ``alembic stamp head`` so the migration-only
    columns the ORM models do not declare are present; otherwise endpoints that
    maintain them (offices/leases/landlords/maintenance create & update) raise a
    database error *after* the row has already been committed, surfacing as a
    spurious 500 (e.g. "Failed to create lease") even though the record persists.
    """
    with sync_engine.begin() as conn:
        for table, source in _SEARCH_VECTOR_SOURCES.items():
            # Guard the interpolated identifiers against an unexpected key. These
            # come from module-level constants, but validating against the
            # registered ORM tables documents intent and prevents a typo here
            # from emitting unintended DDL.
            if table not in Base.metadata.tables:
                raise RuntimeError(f"[start] Unknown table for search_vector setup: {table}")
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_vector tsvector"))
            conn.execute(text(f"UPDATE {table} SET search_vector = to_tsvector('english', {source})"))
            index = _SEARCH_VECTOR_INDEXES[table]
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index} ON {table} "
                    "USING GIN(search_vector) WHERE search_vector IS NOT NULL"
                )
            )
    print("[start] Ensured full-text search_vector columns/indexes exist.")


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
        # ``create_all`` builds tables from the ORM models, which do not declare
        # the migration-only full-text ``search_vector`` columns/indexes. Create
        # them before stamping so endpoints that maintain them don't fail after a
        # commit (a spurious 500 despite the row persisting).
        _ensure_search_vector_columns()
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
    """Create the default admin user on first boot so the app is immediately usable.

    The default admin is a platform super-admin (matching ``seed/run_seed.py``).
    On a fresh database the schema is built via ``create_all`` and Alembic is
    stamped at head, so migration 036 (which promotes ``role='admin'`` accounts
    to super-admin) never actually runs — therefore the super-admin flag must be
    set here explicitly. An existing default admin that predates this is healed
    to super-admin so restarting the container is enough to recover access.
    """
    with Session(sync_engine) as session:
        existing = (
            session.query(User)
            .filter(func.lower(User.email) == settings.DEFAULT_ADMIN_EMAIL.lower())
            .first()
        )
        if existing:
            if not existing.is_super_admin:
                existing.is_super_admin = True
                session.commit()
                print(f"[start] Promoted existing default admin to super-admin: {settings.DEFAULT_ADMIN_EMAIL}")
            else:
                print(f"[start] Admin user already exists: {settings.DEFAULT_ADMIN_EMAIL}")
            return
        admin = User(
            email=settings.DEFAULT_ADMIN_EMAIL,
            display_name="Admin",
            password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
            auth_provider="internal",
            role="admin",
            is_active=True,
            is_super_admin=True,
            organization_id=DEFAULT_ORG_ID,
        )
        session.add(admin)
        session.commit()
        print(f"[start] Created default super-admin user: {settings.DEFAULT_ADMIN_EMAIL}")


def _ensure_super_admins() -> None:
    """Promote any users listed in SUPER_ADMIN_EMAILS to platform super-admin.

    Runs on every container start so access can be restored in an existing
    database simply by setting the env var and redeploying. Matching is
    case-insensitive and idempotent; emails with no matching user are skipped.
    """
    emails = [e.strip() for e in settings.SUPER_ADMIN_EMAILS.split(",") if e.strip()]
    if not emails:
        return
    with Session(sync_engine) as session:
        for email in emails:
            user = (
                session.query(User)
                .filter(func.lower(User.email) == email.lower())
                .first()
            )
            if not user:
                print(f"[start] SUPER_ADMIN_EMAILS: no user found for {email}; skipping.")
                continue
            if user.is_super_admin and user.is_active:
                print(f"[start] SUPER_ADMIN_EMAILS: {email} already super-admin.")
                continue
            user.is_super_admin = True
            user.is_active = True
            print(f"[start] SUPER_ADMIN_EMAILS: promoted {email} to super-admin.")
        session.commit()


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
_ensure_super_admins()


def _ensure_raw_tables() -> None:
    """
    Create tables that are managed by raw SQL (no ORM model) and therefore
    not created by Base.metadata.create_all() on fresh-database deployments.
    Safe to run on every startup — all statements use CREATE TABLE IF NOT EXISTS.
    """
    statements = [
        # Persistent auth rate-limiting (migration 020). Also defined as the
        # ``AuthLockout`` ORM model so ``create_all`` builds it on fresh
        # databases; this CREATE TABLE IF NOT EXISTS is a belt-and-suspenders
        # safeguard that remains harmless when the table already exists.
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


def _run_initial_seed_once() -> None:
    """Run the data seed exactly once against the existing database.

    Imports the spreadsheet data for the default organization the first time the
    container boots against a given database, then records a marker row so the
    seed never runs again on subsequent restarts. The individual importers are
    idempotent, but the marker guarantees the "one time" contract even if data
    is later edited or removed. Best-effort: any failure is logged and never
    prevents the application from starting.
    """
    marker = "initial_default_org_seed"
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS seed_runs ("
                "name VARCHAR(255) PRIMARY KEY, "
                "ran_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        )
        already_run = conn.execute(
            text("SELECT 1 FROM seed_runs WHERE name = :name"), {"name": marker}
        ).first()

    if already_run:
        print(f"[start] Initial data seed already applied ({marker}); skipping.")
        return

    print("[start] Running initial data seed for the default organization (one-time)...")
    try:
        from seed.run_seed import run_seed

        run_seed()
    except SystemExit as exc:
        # run_seed guards on a missing schema by raising SystemExit; surface the
        # message and leave the marker unset so it can retry on a later boot.
        print(f"[start] Initial data seed skipped: {exc}")
        return
    except Exception as exc:  # noqa: BLE001 - best-effort; must never block startup
        print(f"[start] WARNING: initial data seed failed and will be retried next boot: {exc!r}")
        traceback.print_exc()
        return

    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO seed_runs (name) VALUES (:name) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": marker},
        )
    print(f"[start] Initial data seed complete; recorded marker '{marker}'.")


_run_initial_seed_once()


def _run_knowledge_reindex() -> None:
    """Build the AI assistant's knowledge index at startup.

    The portfolio knowledge index (:class:`~app.models.knowledge_chunk.
    KnowledgeChunk`) that powers ``/ai/assistant/query`` is otherwise only
    rebuilt by the 3 AM scheduler job, so a freshly seeded database has an empty
    index until then and the assistant answers "the provided context does not
    contain information" for data that is in fact present.

    Rebuild it once on boot so the seeded portfolio is queryable immediately.
    Indexing is idempotent (each org's chunks are replaced wholesale) and
    degrades gracefully to keyword-only when Gemini is not configured, so this is
    safe to run on every start. Best-effort: any failure is logged and never
    prevents the application from starting.
    """
    print("[start] Building AI assistant knowledge index...")
    try:
        import asyncio

        from app.tasks.knowledge_index import reindex_knowledge

        asyncio.run(reindex_knowledge())
    except Exception as exc:  # noqa: BLE001 - best-effort; must never block startup
        print(f"[start] WARNING: knowledge index build failed: {exc!r}")
        traceback.print_exc()
        return
    print("[start] AI assistant knowledge index built.")


_run_knowledge_reindex()

# Hand off to uvicorn.
sys.exit(subprocess.call([
    "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
]))


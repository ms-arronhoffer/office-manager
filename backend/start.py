"""Startup script: run migrations, ensure admin user, then launch uvicorn."""
import os
import subprocess
import sys
import time
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
            # Only backfill rows that don't yet have a vector. This keeps the
            # call cheap and idempotent on existing databases (where it now runs
            # on every boot), instead of rewriting every row each startup.
            conn.execute(
                text(
                    f"UPDATE {table} SET search_vector = to_tsvector('english', {source}) "
                    "WHERE search_vector IS NULL"
                )
            )
            index = _SEARCH_VECTOR_INDEXES[table]
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index} ON {table} "
                    "USING GIN(search_vector) WHERE search_vector IS NOT NULL"
                )
            )
    print("[start] Ensured full-text search_vector columns/indexes exist.")


# Idempotent reconciliation for newer columns that some long-lived databases
# can be missing: a DB first created on an older release via ``create_all`` +
# ``alembic stamp head`` is marked current, so later feature migrations (the
# email-rule engine in 054, organization scoping in 023) never run on it. The
# email-rules and audit-log pages then 500 on a SELECT for the absent column
# ("Failed to load email rules", blank audit log). Adding the columns with
# ADD COLUMN IF NOT EXISTS is a safe no-op when the migrations already ran.
_RECONCILE_COLUMNS: dict[str, list[str]] = {
    "email_reminder_rules": [
        "organization_id uuid",
        "recipient_roles varchar(20)[]",
        "recipient_user_ids uuid[]",
        "delivery_mode varchar(20) NOT NULL DEFAULT 'immediate'",
        "escalation_offsets integer[]",
        "escalation_recipient_emails varchar(255)[]",
        "require_acknowledgement boolean NOT NULL DEFAULT false",
        "is_active boolean NOT NULL DEFAULT true",
        "last_triggered_at timestamptz",
    ],
    "email_log": [
        "escalation_level integer NOT NULL DEFAULT 0",
    ],
    "activity_log": [
        "organization_id uuid",
    ],
    "email_acknowledgements": [
        "organization_id uuid",
    ],
    "lease_document_chunks": [
        "entity_type varchar(50)",
        "entity_id uuid",
    ],
    "vendors": [
        "is_1099_vendor boolean NOT NULL DEFAULT false",
        "tax_id varchar(20)",
        "tax_id_type varchar(4)",
        "legal_name varchar(255)",
        "tax_classification varchar(20)",
        "default_tax_box varchar(10)",
    ],
    "vendor_payments": [
        "is_reportable boolean",
        "tax_box varchar(10)",
    ],
    "rental_units": [
        "address_line_1 varchar(255)",
        "address_line_2 varchar(255)",
        "city varchar(100)",
        "state varchar(2)",
        "zip_code varchar(10)",
        "property_type varchar(50)",
        "description text",
        "amenities text",
        "year_built integer",
        "available_date date",
    ],
    "residents": [
        "alternate_phone varchar(50)",
        "company varchar(255)",
        "address_line_1 varchar(255)",
        "address_line_2 varchar(255)",
        "city varchar(100)",
        "state varchar(2)",
        "zip_code varchar(10)",
    ],
    "resident_leases": [
        "lease_type varchar(20)",
        "rent_escalation_rate numeric(8, 6)",
        "late_fee_amount numeric(15, 2)",
        "late_fee_grace_days integer",
        "notice_period_days integer",
        "pet_deposit numeric(15, 2)",
        "renewal_option boolean NOT NULL DEFAULT false",
    ],
    # Self storage gained its own Property (facility) and Manager data sets in
    # migrations 100/101. A DB that was create_all-stamped at an older head has
    # ``alembic upgrade`` as a no-op, so these facility/manager link columns can
    # be absent — the self-storage Units/Agreements/Reservations/Rate-plans tabs
    # then 500 on a SELECT for the missing ``facility_id``/``manager_id``. The
    # ``storage_facilities``/``storage_managers`` tables themselves are created
    # (idempotently) by ``_ensure_self_storage_schema`` before this runs.
    #
    # The self-storage tables mix in ``SoftDeleteMixin`` (``is_deleted`` /
    # ``deleted_at``), but migration 100 created ``storage_facilities`` without a
    # ``deleted_at`` column, so a DB that ran that migration 500s on every
    # ``/self-storage/facilities`` SELECT with ``column
    # storage_facilities.deleted_at does not exist``. Heal the soft-delete
    # columns for every self-storage table that mixes them in.
    "storage_units": [
        "facility_id uuid",
        "is_deleted boolean NOT NULL DEFAULT false",
        "deleted_at timestamptz",
    ],
    "storage_agreements": [
        "facility_id uuid",
        "is_deleted boolean NOT NULL DEFAULT false",
        "deleted_at timestamptz",
    ],
    "storage_reservations": [
        "facility_id uuid",
        "is_deleted boolean NOT NULL DEFAULT false",
        "deleted_at timestamptz",
    ],
    "storage_rate_plans": [
        "facility_id uuid",
        "is_deleted boolean NOT NULL DEFAULT false",
        "deleted_at timestamptz",
    ],
    "storage_facilities": [
        "manager_id uuid",
        "is_deleted boolean NOT NULL DEFAULT false",
        "deleted_at timestamptz",
    ],
    "storage_charges": [
        "is_deleted boolean NOT NULL DEFAULT false",
        "deleted_at timestamptz",
    ],
    # The platform Stripe config gained a Starter price id and swapped the
    # fixed Enterprise price id for an Enterprise Product id (Enterprise is now
    # custom-priced per subscriber) in migration 102. A DB create_all-stamped at
    # an older head would 500 the super-admin Billing → Stripe Integration panel
    # without these columns.
    "platform_stripe_config": [
        "price_id_starter varchar(255)",
        "product_id_enterprise varchar(255)",
    ],
    # In-app subscription cancellation/downgrade (migration 103) added these to
    # support "cancel at period end" semantics on Organization.
    "organizations": [
        "cancel_at_period_end boolean NOT NULL DEFAULT false",
        "current_period_end timestamptz",
    ],
}


def _ensure_reconciled_columns() -> None:
    """Add newer columns missing from older create_all-stamped databases."""
    with sync_engine.begin() as conn:
        for table, columns in _RECONCILE_COLUMNS.items():
            # Identifiers come from module constants, but validate against the
            # registered ORM tables (as _ensure_search_vector_columns does) so a
            # typo here can never emit unintended DDL.
            if table not in Base.metadata.tables:
                raise RuntimeError(f"[start] Unknown table for column reconcile: {table}")
            if not inspect(sync_engine).has_table(table):
                continue
            for col in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col}"))
    print("[start] Ensured email-rule/audit-log columns exist.")


def _ensure_self_storage_schema() -> None:
    """Create the self-storage facility/manager tables idempotently.

    Self storage was given its own Property (``storage_facilities``, migration
    100) and Manager (``storage_managers``, migration 101) data sets. A database
    that was create_all-stamped at an older head is marked current, so those
    later migrations never run (``alembic upgrade head`` is a no-op) and the
    tables are absent — the self-storage Properties tab and the shared facility
    lookup used by every other tab then 500 with ``relation
    "storage_facilities" does not exist``.

    ``Table.create(checkfirst=True)`` only issues ``CREATE TABLE`` for a table
    that is not already present, so this is a safe no-op on healthy databases
    (fresh create_all deployments and DBs that ran migrations 100/101). Managers
    are created first because ``storage_facilities.manager_id`` references them.
    The per-column ``facility_id``/``manager_id`` link columns are then healed by
    ``_ensure_reconciled_columns`` for databases whose tables already existed but
    predate those columns.
    """
    from app.models.self_storage import StorageFacility, StorageManager

    StorageManager.__table__.create(bind=sync_engine, checkfirst=True)
    StorageFacility.__table__.create(bind=sync_engine, checkfirst=True)
    print("[start] Ensured self-storage facility/manager tables exist.")


def _wait_for_database() -> None:
    """Block until the database accepts connections before touching the schema.

    In production Postgres runs on RDS (see ``docker-compose.prod.yml``), which
    can still be booting, failing over, or briefly unreachable when the backend
    container starts — there is no local ``db`` service with a healthcheck to
    gate on. Every schema step below (``inspect(sync_engine)``, ``create_all``,
    ``alembic upgrade``) opens a connection on the first call, so if the DB is
    not yet reachable the very first statement raises, ``start.py`` exits 1, and
    the container crash-loops (``Restarting (1)``) instead of waiting the few
    seconds the database needs to come up.

    Poll with ``SELECT 1`` on a short interval up to ``STARTUP_DB_WAIT_SECONDS``
    (default 120s) so a transient outage self-heals without a crash loop. If the
    database is still unreachable after the budget, exit so the orchestrator's
    restart policy takes over — the same failure mode as before, just no longer
    triggered by a database that simply needed a moment to accept connections.
    """
    timeout = int(os.getenv("STARTUP_DB_WAIT_SECONDS", "120"))
    interval = int(os.getenv("STARTUP_DB_WAIT_INTERVAL_SECONDS", "3"))
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            with sync_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"[start] Database is reachable (after {attempt} attempt(s)).")
            return
        except Exception as exc:  # noqa: BLE001 - any connection error should retry
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                sys.exit(
                    f"[start] Database not reachable after {timeout}s "
                    f"({attempt} attempt(s)); last error: {exc!r}"
                )
            print(
                f"[start] Database not ready (attempt {attempt}): {exc!r}; "
                f"retrying in {interval}s ({int(remaining)}s left)."
            )
            time.sleep(interval)


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
        _ensure_self_storage_schema()
        _ensure_reconciled_columns()
        _run_alembic("stamp", "head")
        return

    if not has_alembic_table:
        # Tables exist but Alembic was never tracked. Every database that lands
        # here was built by ``create_all`` (that is the only path this app has
        # ever used to create schema without also writing ``alembic_version``),
        # so its schema reflects whatever the ORM models looked like when
        # ``create_all`` last ran — NOT any particular migration revision.
        #
        # Historically we stamped such a DB at the legacy ``006`` baseline and
        # replayed 007+. That is fundamentally unsafe: the migrations issue bare
        # ``CREATE TABLE`` statements for tables ``create_all`` has already
        # built, so the very first one that already exists aborts the upgrade
        # (``relation "site_settings" already exists``). Because the schema
        # state never advances, the container ``sys.exit``s and crash-loops
        # forever.
        #
        # A ``create_all`` schema is never genuinely "at 006" — even a DB that
        # is only missing a handful of the newest tables already contains almost
        # everything a from-006 replay would try to create. So for *every* shape
        # of DB in this branch we heal like the fresh path instead of replaying:
        # run ``create_all`` (``checkfirst`` builds only the missing tables),
        # reconcile the migration-only artifacts/columns, then stamp at head.
        registered = set(Base.metadata.tables.keys())
        existing = set(inspect(sync_engine).get_table_names())
        missing = registered - existing
        if missing:
            print(
                "[start] Existing tables found but no alembic_version table; "
                f"schema is missing {len(missing)} model table(s) "
                f"({sorted(missing)}). Creating them from models and healing "
                "artifacts before stamping at head."
            )
            # ``create_all`` only issues CREATE TABLE for tables not already
            # present, so this adds the missing tables without touching the
            # existing ones.
            Base.metadata.create_all(bind=sync_engine)
        else:
            print(
                "[start] Existing tables found but no alembic_version table; "
                "schema already matches the current models (an interrupted "
                "create_all+stamp). Healing artifacts and stamping at head."
            )
        _ensure_search_vector_columns()
        _ensure_self_storage_schema()
        _ensure_reconciled_columns()
        _run_alembic("stamp", "head")
        return

    print("[start] Running alembic upgrade head...")
    _run_alembic("upgrade", "head")

    # Create newer tables and reconcile newer columns that a previously
    # create_all-stamped database can be missing (alembic upgrade is a no-op
    # there). Tables first so column reconcile can add their link columns.
    # Idempotent on healthy DBs.
    _ensure_self_storage_schema()
    _ensure_reconciled_columns()
    # The migration-only full-text ``search_vector`` columns/indexes are not
    # declared on the ORM models, so a database first built via ``create_all`` +
    # ``alembic stamp head`` at an older revision is marked as already having
    # migration 018 applied and never actually gets these columns (the upgrade
    # above is a no-op). Heal them here too — otherwise offices/leases/landlords/
    # maintenance create & update raise a DB error *after* the row is committed,
    # surfacing as a spurious 500 (e.g. "Could not create office") even though
    # the record persists. Idempotent (ADD COLUMN IF NOT EXISTS + NULL-only backfill).
    _ensure_search_vector_columns()

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


_wait_for_database()
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


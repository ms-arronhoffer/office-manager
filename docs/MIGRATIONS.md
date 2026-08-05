# Database migration runbook

How schema changes reach a database, what the current migrations do, and the one
case that needs manual attention.

---

## How migrations are applied

`backend/start.py` runs before the API and picks one of three paths. Which path
it takes determines whether your migrations run at all, so read this before
assuming `alembic upgrade head` happened.

| Database state | What happens | Do migrations run? |
|---|---|---|
| **Fresh** (no tables, no `alembic_version`) | `Base.metadata.create_all()` builds every table from the ORM models, then `alembic stamp head` | **No.** Stamped as applied without executing |
| **Legacy** (tables exist, no `alembic_version`) | `create_all(checkfirst)` fills gaps, artifacts are healed, then `alembic stamp head` | **No.** Same as above |
| **Tracked** (has `alembic_version`) | `alembic upgrade head` | **Yes** |

### Why this matters

On a fresh deployment your migration is marked applied but its `upgrade()` body
never executes. Anything a migration creates that is **not declared on an ORM
model** silently does not exist.

`start.py` compensates with `_ensure_*` helpers that run on **every** startup
path, covering artifacts the ORM cannot express: full-text `search_vector`
columns, pgvector `embedding_vec` columns, self-storage schema, reconciled
columns and the manager name constraint. Any new migration that creates
something outside the ORM models must add a helper there, or it will be missing
on every fresh install.

Running Alembic by hand:

```bash
cd backend
alembic upgrade head          # apply everything pending
alembic current               # what this database is at
alembic history --verbose     # the chain
alembic downgrade -1          # step back one revision
```

---

## Current migrations (110 to 117)

| Rev | File | Adds | Fresh-DB safe? |
|---|---|---|---|
| 110 | `110_add_annual_stripe_prices.py` | Annual Stripe price ID columns | Yes, on ORM models |
| 111 | `111_add_resident_payment_methods.py` | `resident_payment_methods`; `autopay_enabled` and `autopay_payment_method_id` on resident leases | Yes, on ORM models |
| 112 | `112_add_pgvector_embeddings.py` | `vector` extension, `embedding_vec` columns, HNSW indexes | Yes, via startup heal |
| 113 | `113_add_org_sso_config.py` | `organization_sso_configs`, `sso_login_states` | Yes, on ORM models |
| 114 | `114_add_external_connections.py` | QuickBooks and Plaid connections, account mapping, sync logs | Yes, on ORM models |
| 115 | `115_add_billable_unit_snapshots.py` | `billable_unit_snapshots` | Yes, on ORM models |
| 116 | `116_active_lease_billing_and_discounts.py` | Monthly active-lease ledger and tracked Stripe discount codes | Yes, on ORM models |
| 117 | `117_default_lease_status_active.py` | Normalize unset lease statuses and default new leases to Active | Yes, on ORM models |

The chain is linear: `109 → 110 → 111 → 112 → 113 → 114 → 115 → 116 → 117`.

---

## pgvector: healed at startup, not by the migration

Migration 112 is the one migration that cannot be relied on to run.

The `embedding_vec` column is deliberately **not** declared on the ORM models.
Declaring it would make `create_all` emit `vector(768)`, which fails outright on
any database without the extension, including the test suite. So on a fresh
database the migration is stamped as applied without executing.

`start.py` therefore heals it directly via `_ensure_pgvector_columns()`, which
emits the same DDL as migration 112 and runs on **all three** startup paths
alongside `_ensure_search_vector_columns()`. **No manual step is required after
a deploy.**

Every step is optional and wrapped in a savepoint, because pgvector is
unavailable on some managed Postgres offerings and a missing extension must
never stop the app from booting. When it cannot be installed, startup logs:

```
[start] pgvector unavailable; embedding search stays on the JSONB + in-Python cosine fallback.
```

That fallback is correct but scans every chunk in application memory, so it does
not scale. Check the boot log if semantic search feels slow.

### Verify

```sql
-- 1. Is the extension installed?
SELECT extname FROM pg_extension WHERE extname = 'vector';

-- 2. Do the columns exist?
SELECT table_name, column_name
FROM information_schema.columns
WHERE column_name = 'embedding_vec';
-- expect: knowledge_chunks, lease_document_chunks

-- 3. Are the HNSW indexes present?
SELECT indexname FROM pg_indexes
WHERE indexname IN ('idx_knowledge_chunks_embedding_hnsw',
                    'idx_lease_doc_chunks_embedding_hnsw');
```

Empty results mean the extension is unavailable on this server. Confirm your
provider supports pgvector and restart the backend; the heal is idempotent and
re-runs on every boot.

The JSONB embedding column is retained as both the fallback and the backfill
source, so existing rows are populated automatically. No data is lost either way.

---

## Pre-flight

Before upgrading a deployed environment:

1. **Back up.** See [backup-setup.md](backup-setup.md). Several of these
   migrations add non-null columns with defaults; a restore is the only clean
   rollback for a partially applied chain.
2. **Set `ENCRYPTION_KEY`.** Revisions 113 and 114 add columns holding encrypted
   OAuth secrets. Without the key, writing to them raises outside a development
   `APP_ENV`. See [INTEGRATIONS.md](INTEGRATIONS.md).
3. **Check the current revision** with `alembic current` so you know which of
   the three paths above you are on.
4. **Confirm pgvector availability** with your Postgres provider if semantic
   search performance matters.

---

## Post-upgrade verification

```bash
cd backend
alembic current      # expect 117 (or later)
```

```sql
-- new tables all present
SELECT table_name FROM information_schema.tables
WHERE table_name IN (
  'resident_payment_methods',
  'organization_sso_configs',
  'sso_login_states',
  'billable_unit_snapshots'
) ORDER BY table_name;
```

Then confirm the pgvector queries above. Startup heals them automatically, so an
empty result means the extension is unavailable on this server rather than a
missed step.

---

## Rollback

Each revision implements `downgrade()`, so `alembic downgrade <rev>` steps back.
Two caveats:

- **Downgrade is lossy.** Dropping `resident_payment_methods` discards saved
  payment tokens; residents must re-add their methods. Dropping the SSO and
  connector tables discards connections, which must be re-established with the
  provider.
- **Downgrade cannot help a fresh-stamped database.** If migrations never ran,
  there is nothing to reverse and `downgrade` will try to drop objects
  `create_all` built. Restore from backup instead.

---

## Adding a migration

1. Number it sequentially and set `down_revision` to the current head. Check
   with `alembic history` first; parallel work has collided here before.
2. Prefer declaring new tables and columns on the ORM models, so `create_all`
   covers fresh installs for free.
3. If a migration creates something the ORM cannot express (extensions, indexes,
   generated columns, raw DDL), **add an `_ensure_*` helper to `start.py`** and
   call it on all three paths, or it will be absent on every fresh install.
   `_ensure_pgvector_columns()` is the worked example.
4. Guard on existence (`IF NOT EXISTS`, `checkfirst`) so the migration is a safe
   no-op on a database that already has the object.
5. Make sure `downgrade()` actually reverses the change.

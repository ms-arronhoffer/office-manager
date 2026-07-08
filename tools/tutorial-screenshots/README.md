# Tutorial screenshot pipeline

Generates every screenshot used by the landing site's `/tutorials` pages —
real, non-mocked captures of the actual product, taken against a
purpose-built demo organization ("Meridian Portfolio Group") with fictional
company, person, and property data.

This is a standalone toolkit (its own `package.json`/`node_modules`) — it is
not part of the app's own test suite and is never shipped to production.

## What gets captured

`manifest.ts` is the single source of truth for which page gets captured for
which persona. Personas mirror the app's real access model:

- **Internal roles** (login with email/password): `admin`, `editor`,
  `accountant`, `viewer` — see `frontend/src/auth/RoleGuard.tsx`.
- **External, token-gated portals**: `resident`, `owner`, `vendor`, `client`
  — each reached via its own invite/signup link, exactly as a real
  resident/owner/vendor/landlord contact would use it.

Each screenshot lands at `landing/public/tutorials/<persona>/<id>.png` and is
referenced by `landing/src/config/tutorialContent.ts`.

## Regenerating screenshots

### One command (recommended)

```bash
cd tools/tutorial-screenshots
./run.sh
```

This boots Postgres + the backend in Docker, builds and serves the frontend
in production mode, seeds the demo org over the REST API, and runs the
Playwright capture — then tears everything down. Requires Docker, Node 20+,
and Python 3.11+.

### Step by step (useful while iterating)

```bash
# 1. Start the backend (from the repo root)
docker compose -f docker-compose_local.yml \
  -f tools/tutorial-screenshots/docker-compose.override.yml \
  --env-file .env up -d --build db backend

# 2. Build + serve the frontend in production mode (avoids React StrictMode's
#    dev-only double-effect invocation, which double-redeems single-use
#    portal invite tokens)
cd frontend
npm install --legacy-peer-deps
VITE_API_BASE_URL=/api/v1 npm run build
VITE_DEV_API_TARGET=http://localhost:8000 npx vite preview --host 0.0.0.0 --port 3000

# 3. In another shell: seed the demo org
cd tools/tutorial-screenshots
pip install -r requirements.txt
python3 seed_demo_org.py --base-url http://localhost:8000 \
  --out demo-org.json --platform-admin-password DemoAdmin123!

# 4. Capture
npm install
npx playwright install --with-deps chromium
APP_BASE_URL=http://localhost:3000 API_BASE_URL=http://localhost:8000 \
  npm run capture
```

## Why a dedicated demo org instead of `backend/seed/`?

`backend/seed/` imports the team's real historical spreadsheets (`backend/seed/data/*.xlsx`),
which is exactly the data this pipeline must *not* put in front of the public.
`seed_demo_org.py` instead creates a brand-new organization ("Meridian
Portfolio Group") through the public signup + authenticated REST API, with
entirely fictional offices, tenants, vendors, residents, and owners. The
generated org is then promoted to the `enterprise` plan (via the platform
super-admin) so every feature-gated screen — HVAC, transitions, digital
waivers, client portal, API keys, webhooks — is reachable for capture,
regardless of which plans are actually for sale.

Re-running the seed script against a fresh database is the normal case (that
is what `run.sh` does). It also tolerates being re-run against an
already-seeded database by logging in instead of re-signing-up, though you
will get duplicate offices/leases/etc. if you do this — prefer a fresh
database (`docker compose down -v`) for a clean capture.

## Redaction / sensitivity review

All names, emails, phone numbers, and dollar figures in the demo org are
invented for this pipeline. Nothing captured here is real customer, tenant,
or financial data. If you extend the manifest to cover a new page, sanity
check the resulting screenshot before committing it — in particular, avoid
capturing any operator-only diagnostic panes that might one day surface
infrastructure details.

## Adding coverage for a new feature

1. Add an entry to `manifest.ts` under the right persona (home multi-role
   features under the *lowest* permission tier that can reach them — e.g. a
   page available to `viewer`, `editor`, and `admin` belongs under `viewer`).
2. If the page needs data that doesn't exist yet, extend `seed_demo_org.py`.
3. Re-run `./run.sh` (or the step-by-step flow) and confirm the new PNG looks
   right.
4. Add a corresponding tutorial (or extend an existing one) in
   `landing/src/config/tutorialContent.ts` / `site.ts`.

## Known gaps

- Insurance certificate creation currently 500s on the backend when a
  `vendor_id` is set (a pre-existing `CertResponse` serialization bug,
  unrelated to this pipeline) — the Insurance Certificates screenshot shows
  the real empty-state UI rather than a populated certificate.

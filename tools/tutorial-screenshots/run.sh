#!/usr/bin/env bash
# Regenerate every tutorial screenshot from a clean slate.
#
# What this does, in order:
#   1. Start Postgres + the backend API in Docker (docker-compose_local.yml).
#   2. Build the frontend for production and serve it locally (vite preview),
#      proxying /api to the backend container — this matches exactly how the
#      real nginx-fronted container serves the app, without hitting the
#      Alpine-npm flakiness some CI/sandbox environments see when building the
#      frontend Docker image itself.
#   3. Seed a purpose-built "demo org" (fake company/people names, no real
#      customer data) via seed_demo_org.py, driven entirely through the public
#      REST API — the same validation and business logic real customers hit.
#   4. Run the Playwright capture spec, which logs in as every internal role
#      and every external portal persona and screenshots the manifest in
#      manifest.ts, writing real, non-mocked PNGs into
#      landing/public/tutorials/<persona>/<id>.png.
#
# Usage:
#   ./run.sh
#
# Requires: Docker + Docker Compose, Node.js 20+, Python 3.11+.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

: "${POSTGRES_PASSWORD:=devpassword123}"
: "${JWT_SECRET:=devjwtsecretdevjwtsecretdevjwtsecret1234}"
: "${DEFAULT_ADMIN_EMAIL:=admin@officemanager.local}"
: "${DEFAULT_ADMIN_PASSWORD:=DemoAdmin123!}"
: "${BACKEND_PORT:=8000}"
: "${APP_PORT:=3000}"

export POSTGRES_PASSWORD JWT_SECRET DEFAULT_ADMIN_EMAIL DEFAULT_ADMIN_PASSWORD

COMPOSE_FILES=(-f "$ROOT_DIR/docker-compose_local.yml" -f "$SCRIPT_DIR/docker-compose.override.yml")

cleanup() {
  echo "Cleaning up..."
  [[ -n "${PREVIEW_PID:-}" ]] && kill "$PREVIEW_PID" 2>/dev/null || true
  docker compose "${COMPOSE_FILES[@]}" down -v || true
}
trap cleanup EXIT

echo "== 1/4: Starting Postgres + backend =="
docker compose "${COMPOSE_FILES[@]}" up -d --build db backend

echo "Waiting for backend readiness..."
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:${BACKEND_PORT}/api/v1/readyz" > /dev/null; then
    echo "Backend is ready."
    break
  fi
  sleep 2
done

echo "== 2/4: Building + serving the frontend =="
pushd "$FRONTEND_DIR" > /dev/null
npm install --legacy-peer-deps
VITE_API_BASE_URL=/api/v1 npm run build
VITE_DEV_API_TARGET="http://localhost:${BACKEND_PORT}" \
  npx vite preview --host 0.0.0.0 --port "$APP_PORT" --strictPort &
PREVIEW_PID=$!
popd > /dev/null

echo "Waiting for frontend readiness..."
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${APP_PORT}/" > /dev/null; then
    echo "Frontend is ready."
    break
  fi
  sleep 2
done

echo "== 3/4: Seeding the demo org =="
pushd "$SCRIPT_DIR" > /dev/null
python3 -m pip install --quiet -r requirements.txt
python3 seed_demo_org.py \
  --base-url "http://localhost:${BACKEND_PORT}" \
  --out demo-org.json \
  --platform-admin-password "$DEFAULT_ADMIN_PASSWORD"

echo "== 4/4: Capturing screenshots =="
rm -rf "$ROOT_DIR/landing/public/tutorials"
npm install
npx playwright install --with-deps chromium
APP_BASE_URL="http://localhost:${APP_PORT}" \
  API_BASE_URL="http://localhost:${BACKEND_PORT}" \
  npx playwright test --config=playwright.config.ts
popd > /dev/null

echo "Done. Screenshots written to landing/public/tutorials/."

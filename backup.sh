#!/usr/bin/env bash
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
ENV_FILE="$(cd "$(dirname "$0")" && pwd)/.backup.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

: "${S3_BUCKET:?S3_BUCKET not set — copy .backup.env.example to .backup.env and fill it in}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
POSTGRES_USER="${POSTGRES_USER:-office_admin}"
POSTGRES_DB="${POSTGRES_DB:-office_manager}"
POSTGRES_HOST="${POSTGRES_HOST:-}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_CLIENT_IMAGE="${POSTGRES_CLIENT_IMAGE:-postgres:18-alpine}"
AWS_SECRET_ID="${AWS_SECRET_ID:-}"
RETENTION_DAYS="${RETENTION_DAYS:-35}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-office-manager}"
DATE=$(date +%Y-%m-%d)
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if ! [[ "$RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]]; then
  echo "RETENTION_DAYS must be a positive integer" >&2
  exit 2
fi

# ── 1. Database backup ────────────────────────────────────────────────────────
log "Backing up database..."
if [[ -n "$POSTGRES_HOST" ]]; then
  if [[ -z "${POSTGRES_PASSWORD:-}" && -n "$AWS_SECRET_ID" ]]; then
    command -v jq >/dev/null || { echo "jq is required to read AWS_SECRET_ID" >&2; exit 3; }
    secret_json="$(aws secretsmanager get-secret-value \
      --region "$AWS_DEFAULT_REGION" --secret-id "$AWS_SECRET_ID" \
      --query SecretString --output text)"
    POSTGRES_PASSWORD="$(printf '%s' "$secret_json" | jq -er '.POSTGRES_PASSWORD')"
    unset secret_json
  fi
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required when POSTGRES_HOST is set}"
  docker run --rm --network host \
    -e PGPASSWORD="$POSTGRES_PASSWORD" \
    "$POSTGRES_CLIENT_IMAGE" \
    pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$POSTGRES_DB" \
    | gzip > "$TMPDIR/db-${DATE}.sql.gz"
else
  docker exec "${COMPOSE_PROJECT}-db-1" \
    pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
    | gzip > "$TMPDIR/db-${DATE}.sql.gz"
fi
log "  Done: $(du -sh "$TMPDIR/db-${DATE}.sql.gz" | cut -f1)"

# ── 2. Uploaded-file evidence ─────────────────────────────────────────────────
if [[ -n "${S3_UPLOAD_BUCKET:-}" ]]; then
  command -v jq >/dev/null || { echo "jq is required for S3 upload manifests" >&2; exit 3; }
  log "Building S3 uploads manifest..."
  aws s3api list-objects-v2 \
    --region "$AWS_DEFAULT_REGION" \
    --bucket "$S3_UPLOAD_BUCKET" \
    --prefix "${S3_UPLOAD_PREFIX:-uploads}" \
    --output json > "$TMPDIR/uploads-raw.json"
  jq --arg bucket "$S3_UPLOAD_BUCKET" \
    '{Bucket: $bucket, GeneratedAt: (now | todate), Contents: (.Contents // [])}' \
    "$TMPDIR/uploads-raw.json" > "$TMPDIR/uploads-manifest-${DATE}.json"
  rm -f "$TMPDIR/uploads-raw.json"
  log "  Manifested $(jq '.Contents | length' "$TMPDIR/uploads-manifest-${DATE}.json") objects."
else
  log "Backing up uploads volume..."
  docker run --rm \
    -v "${COMPOSE_PROJECT}_uploads:/data/uploads:ro" \
    -v "$TMPDIR:/backup" \
    alpine tar czf "/backup/volumes-${DATE}.tar.gz" /data/uploads 2>/dev/null
  log "  Done: $(du -sh "$TMPDIR/volumes-${DATE}.tar.gz" | cut -f1)"
fi

# ── 3. Upload to S3 ───────────────────────────────────────────────────────────
log "Uploading to s3://${S3_BUCKET}..."
aws s3 cp "$TMPDIR/db-${DATE}.sql.gz"      "s3://${S3_BUCKET}/db/db-${DATE}.sql.gz"
if [[ -n "${S3_UPLOAD_BUCKET:-}" ]]; then
  aws s3 cp "$TMPDIR/uploads-manifest-${DATE}.json" \
    "s3://${S3_BUCKET}/uploads-manifests/uploads-manifest-${DATE}.json"
else
  aws s3 cp "$TMPDIR/volumes-${DATE}.tar.gz" "s3://${S3_BUCKET}/volumes/volumes-${DATE}.tar.gz"
fi
log "  Upload complete."

# ── 4. Prune backups older than RETENTION_DAYS ────────────────────────────────
log "Pruning backups older than ${RETENTION_DAYS} days..."
CUTOFF=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%d)
for prefix in db volumes uploads-manifests; do
  while IFS= read -r line; do
    key=$(echo "$line" | awk '{print $4}')
    [[ -z "$key" ]] && continue
    file_date=$(echo "$key" | grep -oP '\d{4}-\d{2}-\d{2}' | head -1)
    if [[ -n "$file_date" && "$file_date" < "$CUTOFF" ]]; then
      log "  Deleting s3://${S3_BUCKET}/${prefix}/${key}"
      aws s3 rm "s3://${S3_BUCKET}/${prefix}/${key}"
    fi
  done < <(aws s3 ls "s3://${S3_BUCKET}/${prefix}/" 2>/dev/null || true)
done

log "Backup finished successfully."

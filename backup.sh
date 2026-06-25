#!/usr/bin/env bash
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
ENV_FILE="$(cd "$(dirname "$0")" && pwd)/.backup.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

: "${S3_BUCKET:?S3_BUCKET not set — copy .backup.env.example to .backup.env and fill it in}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID not set}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY not set}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
POSTGRES_USER="${POSTGRES_USER:-office_admin}"
POSTGRES_DB="${POSTGRES_DB:-office_manager}"
RETENTION_DAYS=3
COMPOSE_PROJECT="office-manager"
DATE=$(date +%Y-%m-%d)
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── 1. Database backup ────────────────────────────────────────────────────────
log "Backing up database..."
docker exec "${COMPOSE_PROJECT}-db-1" \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | gzip > "$TMPDIR/db-${DATE}.sql.gz"
log "  Done: $(du -sh "$TMPDIR/db-${DATE}.sql.gz" | cut -f1)"

# ── 2. Uploads volume backup ──────────────────────────────────────────────────
log "Backing up uploads volume..."
docker run --rm \
  -v "${COMPOSE_PROJECT}_uploads:/data/uploads:ro" \
  -v "$TMPDIR:/backup" \
  alpine tar czf "/backup/volumes-${DATE}.tar.gz" /data/uploads 2>/dev/null
log "  Done: $(du -sh "$TMPDIR/volumes-${DATE}.tar.gz" | cut -f1)"

# ── 3. Upload to S3 ───────────────────────────────────────────────────────────
log "Uploading to s3://${S3_BUCKET}..."
aws s3 cp "$TMPDIR/db-${DATE}.sql.gz"      "s3://${S3_BUCKET}/db/db-${DATE}.sql.gz"
aws s3 cp "$TMPDIR/volumes-${DATE}.tar.gz" "s3://${S3_BUCKET}/volumes/volumes-${DATE}.tar.gz"
log "  Upload complete."

# ── 4. Prune backups older than RETENTION_DAYS ────────────────────────────────
log "Pruning backups older than ${RETENTION_DAYS} days..."
CUTOFF=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%d)
for prefix in db volumes; do
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

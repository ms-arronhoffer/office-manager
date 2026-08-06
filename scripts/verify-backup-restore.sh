#!/usr/bin/env bash
set -euo pipefail

readonly REQUIRED_CONFIRMATION="RESTORE_TO_DISPOSABLE_CONTAINER_ONLY"
: "${CONFIRM_DISPOSABLE_RESTORE:?Set CONFIRM_DISPOSABLE_RESTORE=${REQUIRED_CONFIRMATION}}"
: "${S3_BUCKET:?S3_BUCKET must name the backup bucket without an s3:// prefix}"

if [[ "$CONFIRM_DISPOSABLE_RESTORE" != "$REQUIRED_CONFIRMATION" ]]; then
  echo "Safety confirmation mismatch. Refusing to restore." >&2
  exit 2
fi

# This drill creates and addresses only its own unexposed Docker container.
# Reject conventional external-target variables so a caller cannot repurpose
# the script into restoring over an existing database.
for unsafe_variable in DATABASE_URL RESTORE_DATABASE_URL TARGET_DATABASE_URL PGHOST; do
  if [[ -n "${!unsafe_variable:-}" ]]; then
    echo "$unsafe_variable must be unset. This script never restores to an external database." >&2
    exit 2
  fi
done

for command_name in aws docker gzip; do
  command -v "$command_name" >/dev/null || {
    echo "Required command not found: $command_name" >&2
    exit 3
  }
done

AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-2}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-pgvector/pgvector:pg18}"
RESTORE_SOURCE_ROLE="${RESTORE_SOURCE_ROLE:-office_admin}"
BACKUP_KEY="${BACKUP_KEY:-}"
UPLOADS_MANIFEST_S3_URI="${UPLOADS_MANIFEST_S3_URI:-}"
CONTAINER_NAME="restore-drill-$(date +%s)-$$"
RESTORE_PASSWORD="restore-drill-$RANDOM-$RANDOM"
TMPDIR="$(mktemp -d)"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

if [[ -z "$BACKUP_KEY" ]]; then
  BACKUP_KEY="$(aws s3api list-objects-v2 \
    --region "$AWS_DEFAULT_REGION" \
    --bucket "$S3_BUCKET" \
    --prefix db/db- \
    --query 'sort_by(Contents,&LastModified)[-1].Key' \
    --output text)"
fi

if [[ -z "$BACKUP_KEY" || "$BACKUP_KEY" == "None" || "$BACKUP_KEY" != db/*.sql.gz ]]; then
  echo "No valid db/*.sql.gz backup object was selected." >&2
  exit 4
fi

echo "Downloading s3://${S3_BUCKET}/${BACKUP_KEY}"
aws s3api get-object \
  --region "$AWS_DEFAULT_REGION" \
  --bucket "$S3_BUCKET" \
  --key "$BACKUP_KEY" \
  "$TMPDIR/restore.sql.gz" >/dev/null
gzip -t "$TMPDIR/restore.sql.gz"

if ! [[ "$RESTORE_SOURCE_ROLE" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "RESTORE_SOURCE_ROLE must be a simple PostgreSQL identifier." >&2
  exit 2
fi

docker run -d --rm \
  --name "$CONTAINER_NAME" \
  --label office-manager.restore-drill=true \
  -e POSTGRES_PASSWORD="$RESTORE_PASSWORD" \
  -e POSTGRES_DB=restore_verification \
  "$POSTGRES_IMAGE" >/dev/null

for attempt in $(seq 1 60); do
  if docker exec "$CONTAINER_NAME" pg_isready -U postgres -d restore_verification >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "Disposable PostgreSQL did not become ready." >&2
    exit 5
  fi
  sleep 2
done

docker exec "$CONTAINER_NAME" psql -v ON_ERROR_STOP=1 -U postgres -d restore_verification \
  -c "CREATE ROLE \"${RESTORE_SOURCE_ROLE}\";" >/dev/null

echo "Restoring into disposable container $CONTAINER_NAME"
gzip -dc "$TMPDIR/restore.sql.gz" | docker exec -i "$CONTAINER_NAME" \
  psql -v ON_ERROR_STOP=1 -U postgres -d restore_verification >/dev/null

core_tables=(organizations users offices leases)
for table_name in "${core_tables[@]}"; do
  relation="$(docker exec "$CONTAINER_NAME" psql -At -U postgres -d restore_verification \
    -c "SELECT to_regclass('public.${table_name}')")"
  if [[ "$relation" != "$table_name" ]]; then
    echo "Required table is missing after restore: $table_name" >&2
    exit 6
  fi
done

migration_revision="$(docker exec "$CONTAINER_NAME" psql -At -U postgres -d restore_verification \
  -c "SELECT version_num FROM alembic_version LIMIT 1")"
if [[ -z "$migration_revision" ]]; then
  echo "alembic_version is missing or empty after restore." >&2
  exit 6
fi

echo "Migration revision: $migration_revision"
echo "Core table row counts:"
for table_name in "${core_tables[@]}"; do
  row_count="$(docker exec "$CONTAINER_NAME" psql -At -U postgres -d restore_verification \
    -c "SELECT count(*) FROM public.${table_name}")"
  [[ "$row_count" =~ ^[0-9]+$ ]] || {
    echo "Invalid row count for $table_name: $row_count" >&2
    exit 6
  }
  printf '  %s=%s\n' "$table_name" "$row_count"
done

if [[ -n "$UPLOADS_MANIFEST_S3_URI" ]]; then
  command -v jq >/dev/null || {
    echo "jq is required when UPLOADS_MANIFEST_S3_URI is set." >&2
    exit 3
  }
  [[ "$UPLOADS_MANIFEST_S3_URI" =~ ^s3://([^/]+)/(.+)$ ]] || {
    echo "UPLOADS_MANIFEST_S3_URI must be an s3://bucket/key URI." >&2
    exit 7
  }
  manifest_bucket="${BASH_REMATCH[1]}"
  manifest_key="${BASH_REMATCH[2]}"
  aws s3api get-object --region "$AWS_DEFAULT_REGION" --bucket "$manifest_bucket" \
    --key "$manifest_key" "$TMPDIR/uploads-manifest.json" >/dev/null
  jq -e '.Contents | type == "array"' "$TMPDIR/uploads-manifest.json" >/dev/null
  uploads_bucket="$(jq -r '.Bucket // empty' "$TMPDIR/uploads-manifest.json")"
  [[ -n "$uploads_bucket" ]] || {
    echo "Uploads manifest does not contain a Bucket field." >&2
    exit 7
  }
  manifest_count="$(jq '.Contents | length' "$TMPDIR/uploads-manifest.json")"
  echo "Uploads manifest entries: $manifest_count"

  # Verify up to 20 representative objects still exist without downloading
  # customer content. Empty manifests are valid for deployments with no files.
  while IFS= read -r object_key; do
    aws s3api head-object --region "$AWS_DEFAULT_REGION" \
      --bucket "$uploads_bucket" --key "$object_key" >/dev/null
  done < <(jq -r '.Contents[:20][].Key' "$TMPDIR/uploads-manifest.json")
fi

echo "RESTORE_VERIFICATION_OK backup=s3://${S3_BUCKET}/${BACKUP_KEY}"

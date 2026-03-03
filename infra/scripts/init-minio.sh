#!/usr/bin/env bash
# Phoenix v2 — Create MinIO buckets for skills, backtests, models, code, reports.
# Usage: run inside MinIO container or use mc alias to MinIO endpoint.
# Reference: Milestones.md M1.2.

set -e

# If MC_HOST is set (e.g. in Docker), use it. Otherwise assume local MinIO on 9000.
MC_ALIAS="${MC_ALIAS:-local}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"

buckets="phoenix-skills phoenix-backtests phoenix-models phoenix-code phoenix-reports"

echo "Configuring MinIO at $MINIO_ENDPOINT..."

if command -v mc &>/dev/null; then
  mc alias set "$MC_ALIAS" "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
  for b in $buckets; do
    mc mb "$MC_ALIAS/$b" --ignore-existing
    echo "  Bucket: $b"
  done
  echo "MinIO buckets ready."
else
  echo "Install mc (minio client): https://min.io/docs/minio/linux/reference/minio-mc.html"
  echo "Then create buckets: $buckets"
  exit 1
fi

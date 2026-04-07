#!/bin/bash
# Phoenix API entrypoint — auto-migrates DB schema before starting uvicorn.
#
# - On first run with an empty/legacy DB: creates missing tables via init_db.py
#   and stamps Alembic at the latest revision.
# - On subsequent runs: applies any pending Alembic migrations.
# - Always idempotent and safe to run repeatedly.

set -e

echo "[entrypoint] Phoenix API starting..."
echo "[entrypoint] DATABASE_URL=${DATABASE_URL:-not set}"

# Wait for Postgres to be reachable (max 60s)
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] Waiting for database..."
  for i in $(seq 1 30); do
    if python3 -c "
import asyncio, sys
from sqlalchemy.ext.asyncio import create_async_engine
async def check():
    try:
        engine = create_async_engine('${DATABASE_URL}', pool_pre_ping=True)
        async with engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text('SELECT 1'))
        await engine.dispose()
        return True
    except Exception as e:
        print(f'  db not ready: {e}', file=sys.stderr)
        return False
sys.exit(0 if asyncio.run(check()) else 1)
" 2>/dev/null; then
      echo "[entrypoint] Database is reachable."
      break
    fi
    echo "[entrypoint] db not ready (attempt $i/30), retrying in 2s..."
    sleep 2
  done
fi

# Run init_db.py to create any missing tables (idempotent)
echo "[entrypoint] Running init_db.py to ensure schema..."
PYTHONPATH=/app python3 scripts/init_db.py || {
  echo "[entrypoint] WARNING: init_db.py failed — continuing anyway"
}

# Check current Alembic revision
echo "[entrypoint] Checking Alembic revision..."
CURRENT_REV=$(PYTHONPATH=/app alembic -c shared/db/migrations/alembic.ini current 2>/dev/null | grep -oE '[0-9]+ \(head\)|[0-9]+$' | head -1 | grep -oE '^[0-9]+' || echo "")

if [ -z "$CURRENT_REV" ]; then
  echo "[entrypoint] No Alembic revision found — stamping at head"
  PYTHONPATH=/app alembic -c shared/db/migrations/alembic.ini stamp head || {
    echo "[entrypoint] WARNING: stamp failed"
  }
else
  echo "[entrypoint] Current revision: $CURRENT_REV — running upgrade"
  PYTHONPATH=/app alembic -c shared/db/migrations/alembic.ini upgrade head || {
    echo "[entrypoint] WARNING: alembic upgrade failed — continuing anyway"
  }
fi

echo "[entrypoint] Schema ready. Starting API server..."

# Phase H9: multi-worker via gunicorn + UvicornWorker.
# WEB_CONCURRENCY controls how many worker processes spawn.
# The scheduler uses a Postgres advisory lock so only ONE worker runs cron jobs,
# regardless of how many workers are alive (see services/scheduler.py).
WORKERS=${WEB_CONCURRENCY:-4}

if command -v gunicorn >/dev/null 2>&1; then
  echo "[entrypoint] Starting gunicorn with $WORKERS workers"
  exec gunicorn apps.api.src.main:app \
    --workers "$WORKERS" \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8011 \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    "$@"
else
  echo "[entrypoint] gunicorn not found, falling back to single uvicorn worker"
  exec uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8011 "$@"
fi

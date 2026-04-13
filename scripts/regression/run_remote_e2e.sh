#!/usr/bin/env bash
# Run Playwright E2E tests against a deployed dashboard (not localhost).
#
# Required:
#   export PHOENIX_E2E_BASE_URL="https://your-dashboard-host"
# Optional (for login flows):
#   export PHOENIX_E2E_EMAIL="..."
#   export PHOENIX_E2E_PASSWORD="..."
#
# From repo root:
#   ./scripts/regression/run_remote_e2e.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ -z "${PHOENIX_E2E_BASE_URL:-}" ]]; then
  echo "ERROR: Set PHOENIX_E2E_BASE_URL to your staging/production dashboard URL." >&2
  exit 1
fi

export PYTHONPATH=.
# Do not start local webServer; tests hit remote URL via tests/e2e/conftest.py base_url
exec python3 -m pytest tests/e2e/ -v --tb=short "$@"

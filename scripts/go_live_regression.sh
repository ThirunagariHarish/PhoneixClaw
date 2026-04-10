#!/usr/bin/env bash
# Run full automated go-live regression (same as `make go-live-regression`).
# Optional: set SKIP_E2E=0 and start API + dashboard first, then:
#   SKIP_E2E=0 ./scripts/go_live_regression.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
make go-live-regression
if [[ "${SKIP_E2E:-1}" != "1" ]]; then
  make test-e2e
fi

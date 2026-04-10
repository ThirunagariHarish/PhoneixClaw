#!/usr/bin/env bash
# Minimal API smoke for go-live: GET live-trades returns extended fields when present.
# Usage:
#   export API_BASE_URL=https://your-host   # no trailing slash
#   export JWT_TOKEN=...                    # Bearer token
#   export AGENT_ID=uuid
#   ./scripts/smoke_go_live_api.sh
set -euo pipefail
: "${API_BASE_URL:?Set API_BASE_URL}"
: "${JWT_TOKEN:?Set JWT_TOKEN}"
: "${AGENT_ID:?Set AGENT_ID}"

URL="${API_BASE_URL}/api/v2/agents/${AGENT_ID}/live-trades?limit=5"
echo "GET $URL"
curl -sS -f -H "Authorization: Bearer ${JWT_TOKEN}" "$URL" | python3 -c "
import json, sys
data = json.load(sys.stdin)
assert isinstance(data, list), 'expected JSON array'
keys = ('id', 'ticker', 'side', 'quantity', 'signal_raw', 'broker_order_id', 'decision_status', 'rejection_reason', 'decision_trail')
if not data:
    print('OK: empty trade list (no rows to verify keys)')
    sys.exit(0)
row = data[0]
missing = [k for k in keys if k not in row]
if missing:
    print('FAIL: response missing keys:', missing)
    sys.exit(1)
print('OK: live-trades payload includes extended audit fields')
"

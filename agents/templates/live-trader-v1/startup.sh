#!/usr/bin/env bash
# Agent startup: verify environment and report to Phoenix.
# The agent itself polls for messages — no background pipeline needed.
set -euo pipefail

CONFIG="${1:-config.json}"

if [ ! -f "$CONFIG" ]; then
    echo "[startup] ERROR: $CONFIG not found"
    exit 1
fi

AGENT_ID=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('agent_id',''))" 2>/dev/null || echo "")
if [ -z "$AGENT_ID" ]; then
    echo "[startup] WARNING: agent_id is empty in $CONFIG"
fi

CONNECTOR_ID=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('connector_id',''))" 2>/dev/null || echo "")
if [ -z "$CONNECTOR_ID" ]; then
    echo "[startup] WARNING: connector_id is empty in $CONFIG — messages may not be available"
fi

API_URL=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('phoenix_api_url',''))" 2>/dev/null || echo "")
if [ -z "$API_URL" ]; then
    echo "[startup] WARNING: phoenix_api_url is empty in $CONFIG"
fi

echo "[startup] Agent $AGENT_ID ready (connector=$CONNECTOR_ID)"
echo "[startup] API: $API_URL"
echo "[startup] The agent will poll for messages via check_messages.py"

# Report startup to Phoenix (best-effort)
if [ -f "tools/report_to_phoenix.py" ] && [ -n "$API_URL" ]; then
    python3 tools/report_to_phoenix.py --config "$CONFIG" --action heartbeat 2>/dev/null || true
fi

echo "[startup] Done. Agent is ready to begin polling loop."

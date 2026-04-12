#!/usr/bin/env bash
# Auto-start the signal consumer (live_pipeline or discord_redis_consumer).
# Called by the agent on startup; exits 0 even if already running.
set -euo pipefail

CONFIG="${1:-config.json}"

if pgrep -af "live_pipeline.py" >/dev/null 2>&1; then
    echo "[startup] live_pipeline.py already running"
    exit 0
fi

if pgrep -af "discord_redis_consumer.py" >/dev/null 2>&1; then
    echo "[startup] discord_redis_consumer.py already running"
    exit 0
fi

CONNECTOR_ID=$(python3 -c "import json,sys; c=json.load(open('$CONFIG')); print(c.get('connector_id',''))" 2>/dev/null || echo "")
if [ -z "$CONNECTOR_ID" ]; then
    echo "[startup] WARNING: connector_id is empty in $CONFIG — signal consumer cannot start"
    echo "[startup] Messages will not be received from Redis. Fix connector_ids on the agent config."
    exit 1
fi

if [ -f "tools/live_pipeline.py" ]; then
    echo "[startup] Starting live_pipeline.py (connector_id=$CONNECTOR_ID)..."
    nohup python3 tools/live_pipeline.py --config "$CONFIG" > live_pipeline.log 2>&1 &
    echo "[startup] live_pipeline.py started (PID=$!)"
elif [ -f "tools/discord_redis_consumer.py" ]; then
    echo "[startup] Starting discord_redis_consumer.py (connector_id=$CONNECTOR_ID)..."
    nohup python3 tools/discord_redis_consumer.py --config "$CONFIG" --output pending_signals.json > redis_consumer.log 2>&1 &
    echo "[startup] discord_redis_consumer.py started (PID=$!)"
else
    echo "[startup] ERROR: Neither live_pipeline.py nor discord_redis_consumer.py found in tools/"
    exit 1
fi

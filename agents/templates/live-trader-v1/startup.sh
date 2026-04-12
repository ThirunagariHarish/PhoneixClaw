#!/usr/bin/env bash
# Auto-start the signal consumer (live_pipeline or discord_redis_consumer).
# Called by the agent on startup; exits 0 even if already running.
set -euo pipefail

CONFIG="${1:-config.json}"
PID_FILE="pipeline.pid"

# Agent-scoped liveness check: use a PID file in the agent's own working
# directory rather than a global pgrep (which would collide across agents).
_is_pipeline_alive() {
    if [ ! -f "$PID_FILE" ]; then
        return 1
    fi
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -z "$pid" ]; then
        return 1
    fi
    if kill -0 "$pid" 2>/dev/null; then
        # Verify it is actually a pipeline process (not a recycled PID)
        if cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' | grep -q "live_pipeline\|discord_redis_consumer"; then
            return 0
        fi
        # macOS fallback
        if ps -p "$pid" -o args= 2>/dev/null | grep -q "live_pipeline\|discord_redis_consumer"; then
            return 0
        fi
    fi
    return 1
}

if _is_pipeline_alive; then
    echo "[startup] Pipeline already running (PID=$(cat "$PID_FILE"))"
    exit 0
fi

# Stale PID file — remove it
rm -f "$PID_FILE"

CONNECTOR_ID=$(python3 -c "import json,sys; c=json.load(open('$CONFIG')); print(c.get('connector_id',''))" 2>/dev/null || echo "")
if [ -z "$CONNECTOR_ID" ]; then
    echo "[startup] WARNING: connector_id is empty in $CONFIG — signal consumer cannot start"
    echo "[startup] Messages will not be received from Redis. Fix connector_ids on the agent config."
    exit 1
fi

if [ -f "tools/live_pipeline.py" ]; then
    echo "[startup] Starting live_pipeline.py (connector_id=$CONNECTOR_ID)..."
    nohup python3 tools/live_pipeline.py --config "$CONFIG" > live_pipeline.log 2>&1 &
    PIPELINE_PID=$!
    echo "$PIPELINE_PID" > "$PID_FILE"
    echo "[startup] live_pipeline.py started (PID=$PIPELINE_PID)"
elif [ -f "tools/discord_redis_consumer.py" ]; then
    echo "[startup] Starting discord_redis_consumer.py (connector_id=$CONNECTOR_ID)..."
    nohup python3 tools/discord_redis_consumer.py --config "$CONFIG" --output pending_signals.json > redis_consumer.log 2>&1 &
    PIPELINE_PID=$!
    echo "$PIPELINE_PID" > "$PID_FILE"
    echo "[startup] discord_redis_consumer.py started (PID=$PIPELINE_PID)"
else
    echo "[startup] ERROR: Neither live_pipeline.py nor discord_redis_consumer.py found in tools/"
    exit 1
fi

"""Discord Redis consumer -- replaces the per-agent Discord client.

The centralized message_ingestion daemon (in apps/api/src/services/message_ingestion.py)
publishes every Discord message to Redis stream `stream:channel:{connector_id}`.
Each live agent runs this consumer to read its assigned channel's stream and
process messages through the existing decision_engine.

Benefits over per-agent Discord clients:
- One Discord connection per token (avoids rate limits and conflicts)
- Messages persisted in DB BEFORE delivery (replay on agent restart)
- Single point to fix Discord API quirks
- EOD AutoResearch can inspect every message the agent had available

Usage (called from CLAUDE.md -- runs as persistent daemon until SIGTERM):
    python tools/discord_redis_consumer.py --config config.json --output pending_signals.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Shutdown flag -- set by SIGTERM / SIGINT
# ---------------------------------------------------------------------------
_shutdown = False


def _handle_signal(sig, frame):  # noqa: ARG001
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ---------------------------------------------------------------------------
# Cursor persistence
# ---------------------------------------------------------------------------
CURSOR_FILE = Path("stream_cursor.json")
MAX_PENDING = 500


def _load_cursor(stream_key: str) -> str:
    """Return saved last_id for this stream, or '0-0' on first start."""
    if CURSOR_FILE.exists():
        try:
            data = json.loads(CURSOR_FILE.read_text())
            if data.get("stream_key") == stream_key and data.get("last_id"):
                return data["last_id"]
        except Exception:
            pass
    return "0-0"


def _save_cursor(stream_key: str, last_id: str, count: int) -> None:
    """Persist the stream cursor to disk so restarts resume where we left off."""
    try:
        CURSOR_FILE.write_text(
            json.dumps({
                "stream_key": stream_key,
                "last_id": last_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "message_count": count,
            })
        )
    except Exception as exc:
        print(f"[redis_consumer] cursor save failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def _config(config_path: str = "config.json") -> dict:
    p = Path(config_path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Core consumer coroutine
# ---------------------------------------------------------------------------


async def consume(connector_id: str, output_path: str) -> int:
    """Consume messages from the Redis stream indefinitely until _shutdown is set.

    Returns the total number of messages written during this run.
    """
    global _shutdown

    try:
        import redis.asyncio as aioredis
        import redis.exceptions
    except ImportError:
        print("[redis_consumer] redis-py not installed", file=sys.stderr)
        return 0

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        r = aioredis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        print(f"[redis_consumer] Connect failed: {exc}", file=sys.stderr)
        return 0

    stream_key = f"stream:channel:{connector_id}"
    last_id = _load_cursor(stream_key)
    total_collected = 0
    _backoff = 0

    try:
        while not _shutdown:
            try:
                # Block for up to 5 s waiting for new messages
                result = await r.xread({stream_key: last_id}, count=20, block=5000)
                if not result:
                    continue

                batch: list[dict] = []
                for _stream, entries in result:
                    for msg_id, data in entries:
                        last_id = msg_id
                        batch.append({
                            "stream_id": msg_id,
                            "channel_id": data.get("channel_id", connector_id),
                            "channel": data.get("channel", ""),
                            "author": data.get("author", ""),
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "message_id": data.get("message_id", ""),
                        })

                if batch:
                    _backoff = 0  # successful read resets backoff
                    total_collected += len(batch)

                    # Append to pending_signals.json
                    out = Path(output_path)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    existing: list = []
                    if out.exists():
                        try:
                            existing = json.loads(out.read_text())
                            if not isinstance(existing, list):
                                existing = []
                        except Exception:
                            existing = []
                    existing.extend(batch)
                    # Trim to avoid unbounded growth (Fix 3.1e)
                    if len(existing) > MAX_PENDING:
                        existing = existing[-MAX_PENDING:]
                    out.write_text(json.dumps(existing, indent=2, default=str))
                    print(f"[redis_consumer] Collected {len(batch)} msgs -> {output_path}")

                    # Persist cursor after each successful batch (Fix 3.1b)
                    _save_cursor(stream_key, last_id, total_collected)

            except redis.exceptions.ConnectionError as exc:
                _backoff += 1
                wait = min(2 ** _backoff, 30)
                print(f"[redis_consumer] Redis disconnected, retry in {wait}s: {exc}", file=sys.stderr)
                await asyncio.sleep(wait)
                try:
                    r = aioredis.from_url(redis_url, decode_responses=True)
                    _backoff = 0
                except Exception:
                    pass
            except Exception as exc:
                print(f"[redis_consumer] xread error: {exc}", file=sys.stderr)
                await asyncio.sleep(1)
    finally:
        try:
            await r.aclose()
        except Exception:
            pass

    return total_collected


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Discord Redis consumer (persistent daemon)")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="pending_signals.json")
    # New primary arg -- prefer connector_id from config, fall back to this
    parser.add_argument(
        "--connector-id",
        default=None,
        dest="connector_id",
        help="Override connector_id (DB UUID of the connector)",
    )
    # Deprecated alias -- kept for backward compatibility with older CLAUDE.md invocations
    parser.add_argument(
        "--channel-id",
        default=None,
        dest="channel_id",
        help="[DEPRECATED] Use --connector-id instead",
    )
    # No-op -- kept so legacy CLAUDE.md templates that pass --max-seconds do not error
    parser.add_argument(
        "--max-seconds",
        type=int,
        default=None,
        help="[DEPRECATED/NO-OP] Consumer now runs indefinitely until SIGTERM",
    )
    args = parser.parse_args()

    cfg = _config(args.config)

    # Fix 3.1a: prefer connector_id from config, fall back to channel_id, then CLI args
    connector_id = cfg.get("connector_id") or cfg.get("channel_id") or args.connector_id or args.channel_id
    if not connector_id:
        print("[redis_consumer] No connector_id or channel_id configured", file=sys.stderr)
        sys.exit(1)

    total = asyncio.run(consume(connector_id, args.output))
    print(json.dumps({"connector_id": connector_id, "messages": total}))


if __name__ == "__main__":
    main()

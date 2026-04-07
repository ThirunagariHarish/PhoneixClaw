"""Discord Redis consumer — replaces the per-agent Discord client.

The centralized message_ingestion daemon (in apps/api/src/services/message_ingestion.py)
publishes every Discord message to Redis stream `stream:channel:{channel_id}`.
Each live agent runs this consumer to read its assigned channel's stream and
process messages through the existing decision_engine.

Benefits over per-agent Discord clients:
- One Discord connection per token (avoids rate limits and conflicts)
- Messages persisted in DB BEFORE delivery (replay on agent restart)
- Single point to fix Discord API quirks
- EOD AutoResearch can inspect every message the agent had available

Usage (called from CLAUDE.md run loop):
    python tools/discord_redis_consumer.py --config config.json --output pending_signals.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _config() -> dict:
    p = Path("config.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


async def consume(channel_id: str, output_path: str, max_seconds: int = 30) -> int:
    """Consume messages from Redis stream for `max_seconds`, write to output_path.

    Returns the number of messages written.
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:
        print("  [redis_consumer] redis-py not installed", file=sys.stderr)
        return 0

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis = aioredis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        print(f"  [redis_consumer] Connect failed: {exc}", file=sys.stderr)
        return 0

    stream_key = f"stream:channel:{channel_id}"

    # Read from the stream — start from the latest position
    last_id = "$"
    messages_collected = []
    deadline = time.time() + max_seconds

    try:
        while time.time() < deadline:
            try:
                # Block for up to 5s waiting for a new message
                result = await redis.xread({stream_key: last_id}, count=20, block=5000)
                if not result:
                    continue
                for stream, entries in result:
                    for msg_id, data in entries:
                        last_id = msg_id
                        messages_collected.append({
                            "stream_id": msg_id,
                            "channel_id": data.get("channel_id", channel_id),
                            "channel": data.get("channel", ""),
                            "author": data.get("author", ""),
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "message_id": data.get("message_id", ""),
                        })
            except Exception as exc:
                print(f"  [redis_consumer] xread error: {exc}", file=sys.stderr)
                await asyncio.sleep(1)
    finally:
        try:
            await redis.close()
        except Exception:
            pass

    if messages_collected:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if out.exists():
            try:
                existing = json.loads(out.read_text())
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        existing.extend(messages_collected)
        out.write_text(json.dumps(existing, indent=2, default=str))
        print(f"  [redis_consumer] Collected {len(messages_collected)} msgs → {output_path}")

    return len(messages_collected)


def main():
    parser = argparse.ArgumentParser(description="Discord Redis consumer")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="pending_signals.json")
    parser.add_argument("--max-seconds", type=int, default=30,
                        help="How long to listen before exiting (default 30s)")
    parser.add_argument("--channel-id", default=None,
                        help="Override channel id from config")
    args = parser.parse_args()

    cfg = _config()
    channel_id = args.channel_id or cfg.get("channel_id")
    if not channel_id:
        print("  [redis_consumer] No channel_id configured", file=sys.stderr)
        sys.exit(1)

    count = asyncio.run(consume(channel_id, args.output, args.max_seconds))
    print(json.dumps({"channel_id": channel_id, "messages": count}))


if __name__ == "__main__":
    main()

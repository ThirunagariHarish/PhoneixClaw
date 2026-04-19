"""Signal listener — watches Redis stream and writes incoming signals as individual JSON files.

The Claude agent starts this as a background process. Each signal is written
to ``incoming_signals/<message_id>.json``, one file per message.  The agent
polls the directory and processes files at its own pace.

Usage:
    python signal_listener.py --config config.json [--output-dir incoming_signals]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from shared.observability.metrics import stream_lag_gauge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [signal_listener] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


async def listen(config: dict, output_dir: Path) -> None:
    """Connect to Redis stream and write each message as a JSON file."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.error("redis-py not installed — pip install redis")
        return

    redis_url = config.get("redis_url") or os.getenv("REDIS_URL", "redis://localhost:6379")
    connector_id = config.get("connector_id")
    channel_id = config.get("channel_id", connector_id)

    if not connector_id and not channel_id:
        log.error("config missing both connector_id and channel_id")
        return

    primary_key = f"stream:channel:{connector_id}" if connector_id else None
    fallback_key = f"stream:channel:{channel_id}"

    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        log.error("Redis connect failed: %s", exc)
        return

    stream_key = primary_key or fallback_key
    if primary_key and primary_key != fallback_key:
        try:
            if await redis_client.xlen(primary_key) == 0 and await redis_client.xlen(fallback_key) > 0:
                stream_key = fallback_key
        except Exception:
            pass

    cursor_path = Path("stream_cursor.json")
    last_id = "0-0"
    if cursor_path.exists():
        try:
            cursor_data = json.loads(cursor_path.read_text())
            last_id = cursor_data.get("last_id", "0-0")
        except Exception:
            pass

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Listening on '%s' (cursor=%s), writing to %s/", stream_key, last_id, output_dir)

    total = 0
    last_lag_check = 0.0
    try:
        while True:
            try:
                # Every 30s, compute stream lag
                now_mono = time.monotonic()
                if now_mono - last_lag_check >= 30:
                    try:
                        stream_info = await redis_client.execute_command("XINFO", "STREAM", stream_key)
                        if stream_info and len(stream_info) > 0:
                            info_dict = {stream_info[i]: stream_info[i + 1] for i in range(0, len(stream_info), 2)}
                            last_entry_id_bytes = info_dict.get(b"last-generated-id") or info_dict.get("last-generated-id")
                            if last_entry_id_bytes:
                                last_entry_id = last_entry_id_bytes.decode() if isinstance(last_entry_id_bytes, bytes) else str(last_entry_id_bytes)
                                last_ts = int(last_entry_id.split("-")[0])
                                cursor_ts = int(last_id.split("-")[0]) if last_id != "0-0" else last_ts
                                lag_ms = max(0, last_ts - cursor_ts)
                                stream_lag_gauge.labels(stream_key=stream_key).set(lag_ms / 1000.0)
                    except Exception as exc:
                        log.debug("Stream lag check failed: %s", exc)
                    last_lag_check = now_mono

                result = await redis_client.xread({stream_key: last_id}, count=50, block=5000)
                if not result:
                    continue
                for _stream, entries in result:
                    for msg_id, data in entries:
                        last_id = msg_id
                        total += 1

                        signal = {
                            "stream_id": msg_id,
                            "channel_id": data.get("channel_id", channel_id),
                            "channel": data.get("channel", ""),
                            "author": data.get("author", ""),
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp", ""),
                            "message_id": data.get("message_id", msg_id),
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "correlation_id": data.get("correlation_id", ""),
                        }

                        safe_id = msg_id.replace("-", "_").replace(":", "_")
                        out_path = output_dir / f"{safe_id}.json"
                        out_path.write_text(json.dumps(signal, indent=2))
                        log.info("Signal #%d written: %s (%s)", total, out_path.name,
                                 signal["content"][:60])

                        cursor_path.write_text(json.dumps({"last_id": last_id, "total": total}))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Redis xread error: %s", exc, exc_info=True)
                await asyncio.sleep(2)
    finally:
        try:
            await redis_client.aclose()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Redis signal listener")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output-dir", default="incoming_signals")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    asyncio.run(listen(config, Path(args.output_dir)))


if __name__ == "__main__":
    main()

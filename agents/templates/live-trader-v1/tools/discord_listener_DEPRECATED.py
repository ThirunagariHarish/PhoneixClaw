# DEPRECATED -- This file is scheduled for deletion after the next release cycle.
# It has been superseded by discord_redis_consumer.py.
# DO NOT invoke this tool from any CLAUDE.md or agent script.
# See docs/architecture-agents-tab-fix.md ADR-005 for context.
# Last active reference audit: 2026-04-07
"""Discord channel listener — detects trade signals and queues them for processing.

Priority-based timing:
  - Priority signals (strong BUY/SELL with ticker + price) → emit immediately
  - Per-author 5-second cooldown for burst messages
  - Non-priority signals batch at 15 seconds
  - Emits to asyncio.Queue for consumption by live_pipeline.py
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Signal detection patterns
SIGNAL_PATTERNS = [
    re.compile(r"\$[A-Z]{1,5}", re.IGNORECASE),
    re.compile(r"\b(?:buy|sell|close|trim|took|entered|exit)\b", re.IGNORECASE),
    re.compile(r"\d+[cp]\b", re.IGNORECASE),
    re.compile(r"\b(?:calls?|puts?)\s", re.IGNORECASE),
]

# Priority patterns — explicit trade actions with a ticker
PRIORITY_PATTERNS = [
    re.compile(r"\$[A-Z]{1,5}\s.*\b(?:buy|bought|sell|sold|long|short)\b", re.IGNORECASE),
    re.compile(r"\b(?:buy|bought|sell|sold|long|short)\b.*\$[A-Z]{1,5}", re.IGNORECASE),
    re.compile(r"\$[A-Z]{1,5}\s+\d+[cp]\b", re.IGNORECASE),  # "$SPY 450c"
    re.compile(r"\b(?:entered|exit|close|trim)\b.*\$[A-Z]{1,5}", re.IGNORECASE),
]

AUTHOR_COOLDOWN_SECONDS = 5.0
BATCH_FLUSH_SECONDS = 15.0
DEDUP_WINDOW_SECONDS = 300  # 5-minute dedup window


def is_potential_signal(text: str) -> bool:
    """Check if text contains any signal pattern."""
    return any(p.search(text) for p in SIGNAL_PATTERNS)


def is_priority_signal(text: str) -> bool:
    """Check if text is a high-priority trade signal (explicit action + ticker)."""
    return any(p.search(text) for p in PRIORITY_PATTERNS)


def _message_hash(content: str, author: str) -> str:
    """Create a dedup hash for a message."""
    return hashlib.md5(f"{author}:{content}".encode()).hexdigest()


# Module-level signal queue for integration with live_pipeline.py
signal_queue: asyncio.Queue | None = None


def get_signal_queue() -> asyncio.Queue:
    """Get or create the global signal queue."""
    global signal_queue
    if signal_queue is None:
        signal_queue = asyncio.Queue()
    return signal_queue


async def listen(config: dict):
    try:
        import discord
    except ImportError:
        print("discord.py not installed. Install with: pip install discord.py-self")
        sys.exit(1)

    channel_id = int(config["channel_id"])
    output_file = Path("pending_signals.json")
    queue = get_signal_queue()

    class Listener(discord.Client):
        def __init__(self):
            super().__init__()
            self.buffer: list[dict] = []
            self._author_last_flush: dict[str, float] = {}
            self._seen_hashes: dict[str, float] = {}  # hash → timestamp

        async def on_ready(self):
            print(f"Listening on channel {config.get('channel_name', channel_id)}")
            self.loop.create_task(self._batch_flush_loop())
            self.loop.create_task(self._heartbeat_loop())

        async def on_message(self, message):
            if message.channel.id != channel_id or message.author.bot:
                return
            if not is_potential_signal(message.content):
                return

            # Dedup: skip if we've seen this exact message recently
            msg_hash = _message_hash(message.content, str(message.author))
            now = time.monotonic()
            if msg_hash in self._seen_hashes:
                if now - self._seen_hashes[msg_hash] < DEDUP_WINDOW_SECONDS:
                    return
            self._seen_hashes[msg_hash] = now

            # Clean old dedup entries periodically
            if len(self._seen_hashes) > 1000:
                cutoff = now - DEDUP_WINDOW_SECONDS
                self._seen_hashes = {k: v for k, v in self._seen_hashes.items() if v > cutoff}

            signal = {
                "content": message.content,
                "author": str(message.author),
                "timestamp": message.created_at.isoformat(),
                "message_id": str(message.id),
                "priority": is_priority_signal(message.content),
            }

            author = str(message.author)

            if signal["priority"]:
                # Priority signals: emit immediately if author cooldown allows
                last_flush = self._author_last_flush.get(author, 0)
                if now - last_flush >= AUTHOR_COOLDOWN_SECONDS:
                    self._author_last_flush[author] = now
                    await self._emit_signals([signal])
                else:
                    # Within cooldown — buffer it (will flush on next cooldown expiry)
                    self.buffer.append(signal)
            else:
                # Non-priority: add to buffer for batch flush
                self.buffer.append(signal)

        async def _batch_flush_loop(self):
            """Flush non-priority buffered signals every 15 seconds."""
            while True:
                await asyncio.sleep(BATCH_FLUSH_SECONDS)
                if not self.buffer:
                    continue
                # Also check if any buffered priority signals can now be flushed
                now = time.monotonic()
                ready = []
                still_waiting = []
                for sig in self.buffer:
                    author = sig["author"]
                    last = self._author_last_flush.get(author, 0)
                    if sig["priority"] and now - last < AUTHOR_COOLDOWN_SECONDS:
                        still_waiting.append(sig)
                    else:
                        ready.append(sig)
                        self._author_last_flush[author] = now

                self.buffer = still_waiting
                if ready:
                    await self._emit_signals(ready)

        async def _emit_signals(self, signals: list[dict]):
            """Write signals to file and push to queue."""
            # Write to file for backward compatibility with decision_engine.py CLI
            output_file.write_text(json.dumps(signals, indent=2))

            # Push to async queue for live_pipeline.py
            for sig in signals:
                await queue.put(sig)

            print(json.dumps({
                "event": "signals_ready",
                "count": len(signals),
                "priority": sum(1 for s in signals if s.get("priority")),
                "time": datetime.now(timezone.utc).isoformat(),
            }))
            sys.stdout.flush()

        async def _heartbeat_loop(self):
            """Report heartbeat every 60 seconds."""
            while True:
                await asyncio.sleep(60)
                print(json.dumps({
                    "event": "heartbeat",
                    "buffered": len(self.buffer),
                    "time": datetime.now(timezone.utc).isoformat(),
                }))
                sys.stdout.flush()

    client = Listener()
    await client.start(config["discord_token"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    asyncio.run(listen(config))


if __name__ == "__main__":
    main()

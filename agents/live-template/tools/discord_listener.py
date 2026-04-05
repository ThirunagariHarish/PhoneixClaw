"""Discord channel listener — detects trade signals and queues them for processing."""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


SIGNAL_PATTERNS = [
    re.compile(r"\$[A-Z]{1,5}", re.IGNORECASE),
    re.compile(r"\b(?:buy|sell|close|trim|took|entered|exit)\b", re.IGNORECASE),
    re.compile(r"\d+[cp]\b", re.IGNORECASE),
    re.compile(r"\b(?:calls?|puts?)\s", re.IGNORECASE),
]


def is_potential_signal(text: str) -> bool:
    return any(p.search(text) for p in SIGNAL_PATTERNS)


async def listen(config: dict):
    try:
        import discord
    except ImportError:
        print("discord.py not installed. Install with: pip install discord.py-self")
        sys.exit(1)

    channel_id = int(config["channel_id"])
    output_file = Path("pending_signals.json")

    class Listener(discord.Client):
        def __init__(self):
            super().__init__()
            self.buffer = []

        async def on_ready(self):
            print(f"Listening on channel {config.get('channel_name', channel_id)}")
            self.loop.create_task(self._flush_loop())

        async def on_message(self, message):
            if message.channel.id != channel_id or message.author.bot:
                return
            if not is_potential_signal(message.content):
                return

            self.buffer.append({
                "content": message.content,
                "author": str(message.author),
                "timestamp": message.created_at.isoformat(),
                "message_id": str(message.id),
            })

        async def _flush_loop(self):
            while True:
                await asyncio.sleep(30)
                if not self.buffer:
                    continue
                signals = self.buffer.copy()
                self.buffer.clear()
                output_file.write_text(json.dumps(signals, indent=2))
                print(json.dumps({"event": "signals_ready", "count": len(signals), "time": datetime.now(timezone.utc).isoformat()}))
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

# Spec: Discord Listener

## Purpose

A Python tool that monitors a specific Discord channel for new messages and triggers the agent's inference pipeline when a potential trade signal is detected.

## Design Principles

- Runs as a long-lived Python process (not an LLM call)
- Uses discord.py library for real-time WebSocket connection
- Pre-filters messages with regex/NLP before invoking Claude Code (token optimization)
- Reports to Phoenix API for heartbeat/status

## Implementation

```python
# agents/live-template/tools/discord_listener.py

import asyncio
import json
import subprocess
import discord
from signal_filter import is_potential_signal, parse_quick_signal

class TradeChannelListener(discord.Client):
    def __init__(self, config_path: str):
        super().__init__()
        with open(config_path) as f:
            self.config = json.load(f)
        self.channel_id = int(self.config['channel_id'])
        self.signal_buffer = []
        self.buffer_lock = asyncio.Lock()
    
    async def on_ready(self):
        print(f"Listening on channel {self.config['channel_name']}")
        self.loop.create_task(self._flush_buffer_loop())
    
    async def on_message(self, message):
        if message.channel.id != self.channel_id:
            return
        if message.author.bot:
            return
        
        content = message.content
        
        # Quick pre-filter (regex, no LLM tokens used)
        if not is_potential_signal(content):
            return
        
        signal = parse_quick_signal(content)
        
        async with self.buffer_lock:
            self.signal_buffer.append({
                'content': content,
                'author': str(message.author),
                'timestamp': message.created_at.isoformat(),
                'signal': signal,
                'message_id': str(message.id),
            })
    
    async def _flush_buffer_loop(self):
        """Batch signals every 30 seconds to minimize Claude Code invocations."""
        while True:
            await asyncio.sleep(30)
            async with self.buffer_lock:
                if not self.signal_buffer:
                    continue
                signals = self.signal_buffer.copy()
                self.signal_buffer.clear()
            
            # Write signals to file for Claude Code to process
            with open('pending_signals.json', 'w') as f:
                json.dump(signals, f)
            
            # Notify Claude Code (or let it poll)
            print(f"SIGNAL_BATCH: {len(signals)} signals ready")


def is_potential_signal(text: str) -> bool:
    """Fast regex check — no LLM tokens used."""
    import re
    patterns = [
        r'\$[A-Z]{1,5}',           # Cashtag
        r'(?:buy|sell|close|trim|took|entered|exit)',
        r'\d+[cp]\b',              # Options (e.g., "5950c")
        r'(?:calls?|puts?)\s',
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)
```

## Signal Filtering (Pre-LLM)

```python
# agents/live-template/tools/signal_filter.py

def parse_quick_signal(content: str) -> dict:
    """Extract basic signal info without LLM. Returns None if noise."""
    signal = {
        'type': classify_quick(content),  # 'buy', 'sell', 'close', 'info', 'noise'
        'tickers': extract_tickers(content),
        'price': extract_price(content),
        'confidence': 0.0,
    }
    
    if signal['type'] == 'noise' or not signal['tickers']:
        return None
    
    signal['confidence'] = 0.5 + (0.2 if signal['price'] else 0) + (0.1 if len(signal['tickers']) == 1 else 0)
    return signal
```

## Heartbeat to Phoenix

```python
async def heartbeat_loop(config, interval=60):
    """Report agent health to Phoenix every 60 seconds."""
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/heartbeat",
                    json={
                        'status': 'listening',
                        'channel': config['channel_name'],
                        'uptime_seconds': get_uptime(),
                        'signals_processed_today': get_daily_signal_count(),
                        'trades_today': get_daily_trade_count(),
                    },
                    headers={"Authorization": f"Bearer {config['phoenix_api_key']}"},
                )
        except Exception:
            pass
        await asyncio.sleep(interval)
```

## Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/discord_listener.py` | New |
| `agents/live-template/tools/signal_filter.py` | New |

---

## Standardized Timing

| Action | Interval | Rationale |
|--------|----------|-----------|
| Signal detection flush | Immediate for first signal, then 5s cooldown | Speed is critical; price moves in seconds |
| Position monitoring check | Every 60 seconds | Balance between responsiveness and rate limits |
| Full TA scan | Every 5 minutes | Expensive computation; indicators don't change that fast |
| Heartbeat to Phoenix | Every 60 seconds | Standard liveness check |

The 30-second batch in the current implementation should be changed to **immediate processing** for the first signal, with a 5-second cooldown before processing subsequent signals in the same burst.

```python
async def _flush_buffer_loop(self):
    """Process signals immediately, with 5s cooldown for bursts."""
    while True:
        await asyncio.sleep(1)  # Check every second
        async with self.buffer_lock:
            if not self.signal_buffer:
                continue
            signals = self.signal_buffer.copy()
            self.signal_buffer.clear()

        with open('pending_signals.json', 'w') as f:
            json.dump(signals, f)
        print(f"SIGNAL_BATCH: {len(signals)} signals ready")

        # Cooldown: if analyst posts rapid follow-ups, batch them
        await asyncio.sleep(5)
```

---

## Priority Detection

Messages containing high-priority markers skip the buffer entirely:

```python
PRIORITY_PATTERNS = [
    r'\$[A-Z]{1,5}\s+\d+[cp]',  # Explicit option trade: "$SPY 450c"
    r'(?:bought|sold|entered|closed)\s+\$',  # Action + cashtag
    r'(?:trim|scale|add)\s',  # Position management
]

def is_priority_signal(text: str) -> bool:
    return any(re.search(p, text.lower()) for p in PRIORITY_PATTERNS)
```

Priority signals write immediately to `pending_signals.json` and print `PRIORITY_SIGNAL` to wake Claude Code.

---

## Gateway Reconnection Strategy

Discord WebSocket connections can drop. The listener must handle this gracefully:

```python
RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30, 60]  # Exponential backoff, max 60s

class ResilientListener(TradeChannelListener):
    def __init__(self, config_path: str):
        super().__init__(config_path)
        self._reconnect_attempts = 0

    async def on_disconnect(self):
        delay = RECONNECT_DELAYS[min(self._reconnect_attempts, len(RECONNECT_DELAYS) - 1)]
        log.warning(f"Discord disconnected. Reconnecting in {delay}s (attempt {self._reconnect_attempts + 1})")
        await asyncio.sleep(delay)
        self._reconnect_attempts += 1

    async def on_ready(self):
        self._reconnect_attempts = 0  # Reset on successful connection
        log.info(f"Connected to Discord. Monitoring #{self.config['channel_name']}")
        self.loop.create_task(self._flush_buffer_loop())
        self.loop.create_task(heartbeat_loop(self.config))
```

---

## Discord API Rate Limit Handling

Discord enforces strict rate limits. The listener handles 429 responses:

- Global rate limit: 50 requests per second
- Per-route limits vary
- `discord.py` handles most rate limits internally
- On persistent 429s, back off for the `Retry-After` header duration
- Log all rate limit events for monitoring

---

## Message Deduplication

Analysts sometimes cross-post the same signal to multiple channels. Deduplicate:

```python
from hashlib import sha256

class DeduplicatedListener(ResilientListener):
    def __init__(self, config_path: str):
        super().__init__(config_path)
        self._seen_hashes: set[str] = set()
        self._hash_expiry: dict[str, float] = {}

    def _message_hash(self, content: str, author: str) -> str:
        normalized = re.sub(r'\s+', ' ', content.strip().lower())
        return sha256(f"{author}:{normalized}".encode()).hexdigest()[:16]

    async def on_message(self, message):
        msg_hash = self._message_hash(message.content, str(message.author))
        if msg_hash in self._seen_hashes:
            log.debug(f"Duplicate signal detected, skipping: {msg_hash}")
            return
        self._seen_hashes.add(msg_hash)
        self._hash_expiry[msg_hash] = time.time() + 300  # 5-minute window
        await super().on_message(message)

    async def _cleanup_hashes(self):
        while True:
            now = time.time()
            expired = [h for h, t in self._hash_expiry.items() if t < now]
            for h in expired:
                self._seen_hashes.discard(h)
                del self._hash_expiry[h]
            await asyncio.sleep(60)
```

---

## Graceful Shutdown and Buffer Persistence

On SIGTERM/SIGINT, save any buffered signals to disk before exiting:

```python
import signal

def setup_shutdown_handler(listener):
    def handler(signum, frame):
        log.info("Shutdown signal received. Persisting buffer...")
        if listener.signal_buffer:
            with open('pending_signals.json', 'w') as f:
                json.dump(listener.signal_buffer, f)
            log.info(f"Saved {len(listener.signal_buffer)} buffered signals")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
```

On startup, check for existing `pending_signals.json` and process any leftover signals from a previous crash.

---

## Updated Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/discord_listener.py` | Update — immediate processing + reconnect + dedup |
| `agents/live-template/tools/signal_filter.py` | Update — priority detection |

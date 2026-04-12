# Skill: Discord Channel Monitor

## Purpose
Monitor a specific Discord channel for trade signals from the assigned analyst. Detect buy/sell/close messages in real time and hand them off to the decision engine.

## Trigger
Runs continuously as a persistent daemon process. **Preferred:** `tools/live_pipeline.py --config config.json` (integrated pipeline). **Alternative:** `tools/discord_redis_consumer.py --config config.json --output pending_signals.json` (standalone, writes to file).

Both consume from Redis `stream:channel:{connector_id}` where `connector_id` is the UUID from `config.json`. The Phoenix API ingestion daemon publishes to this stream; the agent does **not** connect to Discord directly.

## Behaviour

### Message Filtering
1. Pre-filter using regex for trade keywords: `$`, ticker patterns (`[A-Z]{1,5}`), price patterns (`\d+\.\d+`), action words (buy, sell, close, trim, add)
2. Ignore messages from bots, non-analyst users, and messages in unrelated threads
3. Priority detection: if message contains `$` or a known ticker, process immediately (skip batch cooldown)

### Batch vs Immediate
- **Immediate**: first signal after quiet period (> 30s since last)
- **Cooldown**: 5-second cooldown between processing to avoid duplicate signals from edited messages
- **Batch**: analyst messages within 30s of each other are grouped as a single signal

### Output
Write detected signals to `pending_signals.json`:
```json
{
  "signals": [{
    "raw_message": "BTO SPX 5950C at 12.50",
    "timestamp": "2026-04-03T09:35:00Z",
    "author": "Vinod",
    "channel": "spx-alerts",
    "parsed": { "action": "BTO", "ticker": "SPX", "strike": 5950, "type": "C", "price": 12.50 }
  }]
}
```

### Reconnection
- If Discord gateway disconnects, reconnect with exponential backoff (1s, 2s, 4s, 8s, max 60s)
- If rate-limited (429), respect `Retry-After` header
- On graceful shutdown, flush pending signals to disk before exit

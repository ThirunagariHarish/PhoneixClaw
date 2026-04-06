# Headline Trading Skill

## Core Principle
Most social media chatter is noise. Your edge is filtering ruthlessly and acting on the rare confirmed signal.

## Signal Quality Tiers

### Tier 1 (Score >= 0.7) — Take immediately
- Multi-source confirmation (Reddit + Twitter both mention)
- Volume surge confirmed (>2x average)
- Price already moving in signal direction
- Action: Standard position size, spawn position monitor

### Tier 2 (Score 0.5-0.7) — Take with reduced size
- Single source but high engagement
- Volume modestly elevated (>1.5x)
- Action: Half position size, tighter stops

### Tier 3 (Score 0.4-0.5) — Watchlist only
- Decent score but no volume confirmation
- Action: Add to watchlist via paper_portfolio.py, monitor for volume

## Anti-Patterns (do NOT trade)
- Single anonymous Reddit post regardless of upvotes
- Sentiment + price contradiction (bullish post but price falling)
- Tickers in middle of earnings IV crush
- Macro event within 4 hours
- Mixed sentiment (>30% bullish AND >30% bearish on same ticker)

## Time Decay
- Reddit signals: act within 30 min of detection
- Twitter signals: act within 5 min of detection (especially "BREAKING")
- After 1 hour, reduce confidence by 50%

## Reporting
For every signal you act on, broadcast knowledge:
```bash
python tools/agent_comms.py --broadcast --intent headline_alert --data signal.json
```

For signals you skip but find interesting, still broadcast — other agents may use them.

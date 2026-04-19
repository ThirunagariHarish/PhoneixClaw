# Narrative Decay Tracker

## Purpose
Track story/narrative freshness via sentiment velocity and decay for catalyst and news-based strategy timing.

## Category
analysis

## API Integration
- Consumes: finnhub-news-sentiment, marketaux-headlines, or similar; No direct API; Processes news/sentiment time series

## Triggers
- When agent needs narrative freshness or sentiment decay
- When user requests catalyst timing, story decay, or sentiment velocity
- When building news-based entry/exit (fade vs follow)
- When assessing if a narrative is "played out"

## Inputs
- `sentiment_series`: object[] — [{timestamp, symbol, sentiment_score, headline}]
- `symbol`: string — Ticker to track
- `decay_half_life`: number — Hours for sentiment to halve (default: 24)
- `velocity_window`: number — Hours for velocity calc (default: 6)
- `min_articles`: number — Min articles for valid decay (default: 3)

## Outputs
- `current_sentiment`: number — Latest aggregate sentiment
- `sentiment_velocity`: number — Change in sentiment over window (positive = accelerating)
- `narrative_freshness`: string — "fresh", "maturing", "decaying", "stale"
- `decay_score`: number — 0-1; 1 = fresh, 0 = stale
- `metadata`: object — Symbol, window, computed_at

## Steps
1. Parse sentiment_series; sort by timestamp
2. Compute current_sentiment: recent articles weighted by recency
3. Compute sentiment_velocity: (sentiment_now - sentiment_window_ago) / window_hours
4. Apply decay model: exponential decay with half_life
5. Derive narrative_freshness from velocity and decay_score
6. fresh: high velocity, high score; stale: low velocity, low score
7. Return current_sentiment, velocity, freshness, decay_score
8. Cache with 1h TTL; update as new news arrives

## Example
```
Input: sentiment_series=[{timestamp:"2025-03-03T10:00Z",sentiment:0.8},{timestamp:"2025-03-03T14:00Z",sentiment:0.6}], symbol="NVDA"
Output: {
  current_sentiment: 0.65,
  sentiment_velocity: -0.05,
  narrative_freshness: "maturing",
  decay_score: 0.55,
  metadata: {symbol:"NVDA", window:6, computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- High velocity + fresh = narrative accelerating; consider following
- Low velocity + stale = narrative played out; consider fading
- Half-life configurable per narrative type (earnings vs macro)

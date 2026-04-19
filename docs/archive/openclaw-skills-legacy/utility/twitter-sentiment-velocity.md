# Twitter Sentiment Velocity

## Purpose
Track how fast a cashtag is trending on X/Twitter to gauge momentum and retail interest.

## Category
utility

## Triggers
- When user requests Twitter/X trending velocity for a cashtag
- When assessing retail momentum or FOMO for a symbol
- When building social sentiment signals for trade timing
- When screening for accelerating or decelerating buzz

## Inputs
- `cashtag`: string — Cashtag (e.g., $AAPL, $NVDA)
- `lookback_hours`: number — Hours for velocity calc (default: 24)
- `granularity`: string — "hourly", "15m" (default: "hourly")
- `api_key`: string — Twitter/X API key or from env
- `include_sentiment`: boolean — Include sentiment score (default: true)

## Outputs
- `velocity`: number — Rate of change of mention count (mentions per hour)
- `acceleration`: number — Change in velocity (positive = accelerating)
- `mention_counts`: object[] — [{timestamp, count}] time series
- `trend_direction`: string — "accelerating", "decelerating", "stable"
- `sentiment_trend`: string — "improving", "declining", "stable" (if include_sentiment)
- `metadata`: object — cashtag, lookback, computed_at

## Steps
1. Fetch tweet counts or mentions for cashtag over lookback_hours (Twitter API, or third-party)
2. Build time series of mention counts at granularity
3. velocity = derivative of mention count (e.g., linear regression slope)
4. acceleration = derivative of velocity
5. trend_direction: acceleration > 0 = accelerating, < 0 = decelerating, else stable
6. If include_sentiment: fetch sentiment scores; sentiment_trend from score trend
7. Return velocity, acceleration, mention_counts, trend_direction, sentiment_trend, metadata
8. Respect rate limits; cache with 15m TTL

## Example
```
Input: cashtag="$NVDA", lookback_hours=24
Output: {
  velocity: 125,
  acceleration: 18,
  mention_counts: [{timestamp: "2025-03-03T14:00:00Z", count: 1200}, ...],
  trend_direction: "accelerating",
  sentiment_trend: "improving",
  metadata: {cashtag: "$NVDA", lookback: 24, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Twitter API v2 or third-party (e.g., SocialBlade, Brandwatch) for mention data
- Velocity spikes often precede price moves; combine with wsb-fomo-tracker
- Consider rate limits and API costs

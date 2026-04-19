# Skill: Social Sentiment Collector

## Purpose
Collect and aggregate sentiment from multiple social media sources (Twitter/X, Reddit, Discord, StockTwits) into a unified sentiment score for trading signals.

## Triggers
- When the agent needs combined social sentiment for a symbol
- When user requests social sentiment aggregation
- When building multi-source sentiment pipelines
- When validating signals against crowd sentiment

## Inputs
- `symbols`: string[] — Tickers to collect sentiment for
- `sources`: string[] — ["twitter", "reddit", "discord", "stocktwits"] or subset
- `lookback_hours`: number — Hours of content to include (default: 24)
- `aggregation`: string — "weighted_avg", "max", "min", or "median"

## Outputs
- `sentiment_by_symbol`: object — Per-symbol aggregated score (-1 to 1)
- `raw_scores`: object — Per-source scores before aggregation
- `mention_volume`: object — Post/mention count per symbol per source
- `metadata`: object — Fetch time, sources_used

## Steps
1. Invoke source-specific skills: Reddit fetcher, Discord reader, Twitter/StockTwits APIs
2. For each source, run sentiment scoring on fetched content (use sentiment-scorer skill)
3. Collect per-symbol scores: {symbol: {source: score, ...}}
4. Normalize scores to -1 (bearish) to 1 (bullish) if source uses different scale
5. Apply aggregation: weighted_avg (by volume), max, min, or median across sources
6. Compute mention_volume: count of posts/tweets per symbol per source
7. Optionally weight by recency (exponential decay for older content)
8. Handle missing data: if a source has no data for symbol, exclude from that source's contribution
9. Return sentiment_by_symbol, raw_scores, mention_volume, metadata
10. Log data quality metrics (coverage, staleness) for monitoring

## Example
```
Input: symbols=["NVDA"], sources=["reddit", "twitter", "stocktwits"], lookback_hours=12
Output: {
  sentiment_by_symbol: {NVDA: 0.65},
  raw_scores: {NVDA: {reddit: 0.72, twitter: 0.58, stocktwits: 0.68}},
  mention_volume: {NVDA: {reddit: 450, twitter: 1200, stocktwits: 320}},
  metadata: {fetched_at: "2025-03-03T15:00:00Z", sources: 3}
}
```

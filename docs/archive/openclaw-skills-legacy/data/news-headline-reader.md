# Skill: News Headline Reader

## Purpose
Aggregate news headlines from multiple sources (Reuters, Bloomberg, Benzinga, etc.) to capture catalysts, earnings, and market-moving events for trading decisions.

## Triggers
- When the agent needs news for a symbol or sector
- When user requests news aggregation or headline monitoring
- When building catalyst-based signal pipelines
- When assessing event risk around positions

## Inputs
- `symbols`: string[] — Tickers to filter news (empty = general market)
- `sources`: string[] — Optional: ["reuters", "bloomberg", "benzinga", "cnbc"]
- `lookback_hours`: number — Hours of news to fetch (default: 24)
- `limit`: number — Max headlines per symbol (default: 20)
- `categories`: string[] — Optional: "earnings", "analyst", "ipo", "merger"

## Outputs
- `headlines`: object[] — Title, summary, source, url, published_at, related_symbols
- `symbol_coverage`: object — Headline count per symbol
- `metadata`: object — Fetch time, sources_queried

## Steps
1. Resolve news API clients for each configured source (NewsAPI, Benzinga, Polygon News)
2. For each symbol, query news endpoints with symbol filter and time range
3. Deduplicate by title similarity or URL across sources
4. Parse each article: title, summary (if available), source, url, published_at
5. Extract related symbols from headline text using ticker regex
6. Apply category filter if specified (earnings, analyst upgrades, etc.)
7. Sort by published_at descending; apply limit per symbol
8. Build symbol_coverage map: symbol -> list of headline ids
9. Optionally fetch full article text for sentiment if configured
10. Return headlines array with metadata

## Example
```
Input: symbols=["NVDA", "AAPL"], lookback_hours=12, limit=10
Output: {
  headlines: [{title: "NVIDIA beats Q4 estimates", source: "Reuters", published_at: "2025-03-03T13:00:00Z", symbols: ["NVDA"]}],
  symbol_coverage: {NVDA: 8, AAPL: 5},
  metadata: {fetched_at: "2025-03-03T15:00:00Z", sources: ["reuters", "benzinga"]}
}
```

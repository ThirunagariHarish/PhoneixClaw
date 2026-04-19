# Skill: Gap Analyzer

## Purpose
Analyze overnight or intraday gaps (open vs prior close) to identify gap-and-go, gap-fill, or fade opportunities based on gap size and context.

## Triggers
- When the agent needs gap analysis for symbols
- When user requests gap plays or gap-fill setups
- When building pre-market or opening watchlists
- When validating gap-based entries

## Inputs
- `symbols`: string[] — Tickers to analyze
- `gap_type`: string — "overnight", "intraday", or "both"
- `min_gap_pct`: number — Minimum gap size in % to consider (default: 1)
- `fill_threshold`: number — % of gap filled to consider "filled" (default: 90)
- `timeframe`: string — "1d" for overnight; "5m"/"15m" for intraday

## Outputs
- `gaps_up`: object[] — Symbols with gap up; size, fill status, current price
- `gaps_down`: object[] — Symbols with gap down
- `fill_status`: object — Per-symbol: "unfilled", "partial", "filled"
- `metadata`: object — Scan time, gap_type, thresholds

## Steps
1. Fetch prior close and current open (or session open) via market-data-fetcher
2. Gap % = (open - prior_close) / prior_close * 100
3. Filter by min_gap_pct (absolute value)
4. For fill status: compare current price to gap range
5. Gap up: filled if price <= prior_close + (gap * (1 - fill_threshold/100))
6. Gap down: filled if price >= prior_close - (|gap| * (1 - fill_threshold/100))
7. Classify: unfilled, partial (< fill_threshold), filled
8. Return gaps_up, gaps_down with size and fill_status
9. Cache with intraday TTL

## Example
```
Input: symbols=["NVDA","AAPL"], gap_type="overnight", min_gap_pct=2
Output: {
  gaps_up: [{symbol: "NVDA", gap_pct: 3.2, fill_status: "partial", current: 878}],
  gaps_down: [],
  fill_status: {NVDA: "partial", AAPL: "unfilled"},
  metadata: {scanned_at: "2025-03-03T09:35:00Z", gap_type: "overnight"}
}
```

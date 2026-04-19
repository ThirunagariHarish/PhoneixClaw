# Seasonality Agent

## Purpose
Adjust bias based on monthly/yearly seasonal patterns (Santa Rally, Sell in May, January effect, etc.).

## Category
advanced-ai

## Triggers
- When evaluating market bias or strategy selection
- When user requests seasonal outlook or calendar effect
- At start of month or key dates (e.g., Nov 1, May 1)
- When adjusting sector exposure for seasonal patterns

## Inputs
- `current_date`: string — ISO date or "today"
- `lookback_years`: number — Years of historical data for pattern (default: 20)
- `patterns`: string[] — ["santa_rally", "sell_in_may", "january_effect", "all"] (default: all)
- `output_format`: string — "bias", "score", "full" (default: full)

## Outputs
- `seasonal_bias`: string — "bullish", "bearish", "neutral"
- `active_patterns`: object[] — [{name, direction, strength, duration}]
- `score`: number — Aggregate seasonal score (-1 to 1)
- `next_key_date`: string — Next significant seasonal date
- `metadata`: object — current_date, lookback, patterns_checked

## Steps
1. Parse current_date; get month, day, week of year
2. Apply patterns: Santa Rally (Nov 15–Jan 5), Sell in May (May–Oct), January effect (Jan 1–15)
3. For each pattern: check if current date in window; assign direction and strength
4. strength from historical avg return in that window (lookback_years)
5. Aggregate: score = weighted sum of active pattern strengths
6. seasonal_bias = score > 0.1 ? bullish : score < -0.1 ? bearish : neutral
7. next_key_date = next pattern start (e.g., May 1 for Sell in May)
8. Return seasonal_bias, active_patterns, score, next_key_date, metadata

## Example
```
Input: current_date="2025-12-15", patterns=["all"]
Output: {
  seasonal_bias: "bullish",
  active_patterns: [{name: "santa_rally", direction: "bullish", strength: 0.8, duration: "Nov15-Jan5"}],
  score: 0.65,
  next_key_date: "2026-05-01",
  metadata: {current_date: "2025-12-15", lookback: 20, patterns_checked: ["santa_rally", "sell_in_may", "january_effect"]}
}
```

## Notes
- Historical patterns don't guarantee future; use as tilt, not sole signal
- Data from historical returns (fred-economic-data, SPY)
- Integrate with macro-regime-detector for regime-aware seasonality

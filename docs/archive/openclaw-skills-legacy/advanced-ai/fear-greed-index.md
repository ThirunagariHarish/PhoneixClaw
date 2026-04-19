# Fear & Greed Index

## Purpose
Integrate CNN Fear & Greed Index to adjust trading aggressiveness and position sizing.

## Category
advanced-ai

## Triggers
- When user requests Fear & Greed Index value
- When adjusting risk or position size based on market sentiment
- When building contrarian or momentum overlays
- Periodically for sentiment dashboard (e.g., daily)

## Inputs
- `index_source`: string — "cnn" or API URL (default: "cnn")
- `include_components`: boolean — Include component breakdown (default: false)
- `lookback_days`: number — Days of history for trend (default: 7)
- `cache_ttl_minutes`: number — Cache duration (default: 60)

## Outputs
- `value`: number — Fear & Greed Index 0–100 (0=extreme fear, 100=extreme greed)
- `classification`: string — "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
- `trend`: string — "rising", "falling", "stable" (from lookback)
- `suggested_action`: string — "reduce_aggression", "neutral", "increase_aggression"
- `components`: object — {put_call, junk_bond, market_momentum, ...} if include_components
- `metadata`: object — source, computed_at

## Steps
1. Fetch Fear & Greed Index from CNN (scrape or API) or configured source
2. Parse value (0–100); map to classification via thresholds
3. Fetch historical values for lookback_days; compute trend (slope)
4. suggested_action: Extreme Fear -> increase_aggression (contrarian), Extreme Greed -> reduce_aggression
5. If include_components: fetch component breakdown (put/call, junk bond, momentum, etc.)
6. Return value, classification, trend, suggested_action, components, metadata
7. Cache with cache_ttl_minutes (CNN updates daily; 60m reasonable)

## Example
```
Input: include_components=false, lookback_days=7
Output: {
  value: 72,
  classification: "Greed",
  trend: "rising",
  suggested_action: "reduce_aggression",
  components: null,
  metadata: {source: "cnn", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- CNN Fear & Greed: https://www.cnn.com/markets/fear-and-greed
- Extreme readings: consider scaling down size or taking profits
- Integrate with regime-adaptive and drawdown-recovery-mode for risk tuning

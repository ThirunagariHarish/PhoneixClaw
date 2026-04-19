# Whale Pattern Recognizer

## Purpose
Recognize institutional accumulation/distribution patterns from options flow, dark pool, and block trade data.

## Category
advanced-ai

## Triggers
- When analyzing options flow for institutional activity
- When user requests whale or smart money detection
- When screening for accumulation/distribution before price moves
- When building signals from unusual-whales or dark pool data

## Inputs
- `flow_data`: object[] — Options flow: [{symbol, strike, expiry, side, premium, size, timestamp}]
- `dark_pool_data`: object[] — Dark pool prints (optional)
- `block_data`: object[] — Block trades (optional)
- `lookback_hours`: number — Window for pattern detection (default: 24)
- `min_premium`: number — Min premium to consider (filter noise) (default: 100000)
- `symbols`: string[] — Optional: filter to symbols
- `pattern_types`: string[] — ["accumulation", "distribution", "sweep", "split_strike"] or "all"

## Outputs
- `patterns`: object[] — [{type, symbol, confidence, size_premium, description}]
- `accumulation_score`: number — Aggregate accumulation signal (0–1) per symbol
- `distribution_score`: number — Aggregate distribution signal (0–1) per symbol
- `whale_activity`: object — Top symbols by premium, net direction
- `metadata`: object — lookback, flow_count, pattern_count

## Steps
1. Load flow_data; filter by min_premium, symbols, lookback
2. Accumulation: large calls bought, OTM calls, put selling; net positive flow
3. Distribution: large puts bought, call selling; net negative flow
4. Sweep: multi-exchange aggressive buys/sells in short window
5. Split strike: related strikes (e.g., diagonal) in same timeframe
6. Compute confidence from size, consistency, and historical accuracy
7. Aggregate accumulation_score, distribution_score per symbol
8. Rank whale_activity by premium and net direction
9. Return patterns, accumulation_score, distribution_score, whale_activity, metadata
10. Integrate with options-flow-analyzer, unusual-whales-flow for data

## Example
```
Input: flow_data=[...], lookback_hours=24, min_premium=100000, pattern_types=["accumulation","distribution"]
Output: {
  patterns: [
    {type: "accumulation", symbol: "NVDA", confidence: 0.88, size_premium: 2.5e6, description: "Large call buying, OTM sweeps"},
    {type: "distribution", symbol: "TSLA", confidence: 0.72, size_premium: 1.2e6, description: "Put buying, call selling"}
  ],
  accumulation_score: {NVDA: 0.85, AAPL: 0.45},
  distribution_score: {TSLA: 0.72, META: 0.38},
  whale_activity: [{symbol: "NVDA", premium: 2.5e6, direction: "bullish"}, ...],
  metadata: {lookback: 24, flow_count: 150, pattern_count: 5}
}
```

## Notes
- Use unusual-whales-flow, dark-pool-volume for data sources
- Historical backtest of pattern -> price move improves confidence calibration
- False positives common; use as one input in multi-factor signal

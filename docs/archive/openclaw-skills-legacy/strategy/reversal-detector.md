# Reversal Detector

## Purpose
Detect potential trend reversals using multiple signals: divergence, exhaustion, structure breaks, and momentum shifts.

## Category
strategy

## Triggers
- When user requests reversal signals or trend change detection
- When agent needs to identify exhaustion in extended moves
- When building counter-trend or reversal entries
- When validating divergence or structure break signals

## Inputs
- `symbol`: string — Ticker to analyze (string)
- `timeframe`: string — Chart interval: "1h", "4h", "1d" (string)
- `signals_enabled`: string[] — "divergence", "structure", "momentum", "volume" (string[])
- `lookback_bars`: number — Bars for analysis (number, default: 50)
- `confirmation_required`: number — Min signals to confirm reversal (number, default: 2)

## Outputs
- `reversal_signal`: string — "bullish", "bearish", "none" (string)
- `signals_detected`: object[] — List of signals that fired (object[])
- `strength`: number — Confidence score 0-100 (number)
- `key_levels`: object — Break levels, invalidation (object)
- `metadata`: object — Timeframe, lookback, scan time (object)

## Steps
1. Fetch OHLCV and optionally RSI/MACD for symbol and timeframe
2. Divergence: price makes new high/low but RSI does not (bearish/bullish div)
3. Structure: break of trendline or key support/resistance
4. Momentum: RSI oversold/overbought with reversal candle (e.g., hammer, engulfing)
5. Volume: climax volume at extremes suggesting exhaustion
6. Score each signal; aggregate into composite strength
7. Require confirmation_required signals to trigger reversal_signal
8. Define key_levels: invalidation below/above for stop placement
9. Return reversal_signal, signals_detected, strength, key_levels
10. Include metadata with timeframe and params

## Example
```
Input: symbol="NVDA", timeframe="4h", signals_enabled=["divergence","structure","momentum"]
Output: {
  reversal_signal: "bearish",
  signals_detected: [{type: "divergence", detail: "price_high_rsi_lower"}, {type: "structure", detail: "trendline_break"}],
  strength: 72,
  key_levels: {invalidation: 890, break_level: 875},
  metadata: {timeframe: "4h", lookback: 50}
}
```

## Notes
- Reversals are probabilistic; use strict risk management
- Multiple timeframe confirmation improves reliability
- Avoid fighting strong trends; reversals work best at extremes

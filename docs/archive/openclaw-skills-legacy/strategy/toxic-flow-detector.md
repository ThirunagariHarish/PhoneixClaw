# Toxic Flow Detector

## Purpose
Detect "toxic" order flow (adverse selection, HFT front-running) using time & sales analysis to avoid trading against informed or predatory flow.

## Category
strategy

## Triggers
- When analyzing order flow before entry
- When time & sales show unusual aggressor imbalance
- When price moves against expected direction despite volume

## Inputs
- timeAndSales: tick-level tape with aggressor side (array)
- volumeProfile: volume at price levels (object)
- spreadHistory: bid-ask spread over lookback (array)

## Outputs
- toxicScore: 0–100 toxicity likelihood (number)
- signal: AVOID | CAUTION | CLEAR (string)
- dominantSide: BUY | SELL | NEUTRAL (string)

## Steps
1. Compute aggressor imbalance (buy vs sell volume) over rolling 1–5 min window
2. Detect sweep patterns: large single prints eating multiple levels
3. Flag front-running: price moves before your intended level is hit
4. Score toxicity: combine imbalance skew, sweep frequency, spread widening
5. Emit AVOID when score > 70, CAUTION when 40–70, CLEAR when < 40

## Example
```yaml
inputs:
  timeAndSales: [{price: 450.25, size: 500, side: SELL}, ...]
  volumeProfile: {450.20: 12000, 450.25: 8000}
outputs:
  toxicScore: 78
  signal: AVOID
  dominantSide: SELL
```

## Notes
- Best used pre-entry; do not override with other signals when AVOID
- Works best in liquid names (SPY, QQQ, SPX); less reliable in illiquid underlyings

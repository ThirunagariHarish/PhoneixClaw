# Whale Flow Follower

## Purpose
Follow institutional whale options flow with defined entry and exit rules based on size, premium, and timing.

## Category
strategy

## Triggers
- When unusual options activity is detected (size > 10x avg)
- When premium is significant (> $1M notional)
- When flow aligns with technical or fundamental thesis

## Inputs
- flow: [{symbol, strike, expiry, type, premium, size, side}, ...] (array)
- spotPrice: underlying price (number)
- flowAge: minutes since flow (number)
- technicalBias: BULLISH | BEARISH | NEUTRAL (string)

## Outputs
- signal: FOLLOW_LONG | FOLLOW_SHORT | IGNORE (string)
- confidence: 0–100 (number)
- suggestedStrike: strike to mirror (number)
- expiry: suggested expiry (string)
- holdTime: minutes to hold (number)
- stopLevel: invalidation price (number)

## Steps
1. Filter: premium > $500k; size > 10x avg; flow age < 30 min
2. Classify: calls = bullish; puts = bearish; check spread vs single
3. Confirm with technical bias; boost confidence when aligned
4. FOLLOW_LONG when large call flow + bullish bias; FOLLOW_SHORT for puts
5. Suggested strike = same or adjacent; hold 30–90 min
6. Stop = prior swing or flow entry level; exit if flow reverses

## Example
```yaml
inputs:
  flow: [{symbol: SPY, strike: 450, type: CALL, premium: 1200000, side: BID}]
  technicalBias: BULLISH
  flowAge: 5
outputs:
  signal: FOLLOW_LONG
  confidence: 78
  suggestedStrike: 450
  holdTime: 60
  stopLevel: 447.50
```

## Notes
- Whale flow can be hedges; not all flow is directional
- Verify with tape; dark pool or block prints add confidence

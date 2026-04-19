# EOD SPX Composite

## Purpose
End-of-day SPX composite strategy combining MOC imbalance, GEX, Charm, and 0DTE skew for final 30–60 minutes.

## Category
strategy

## Triggers
- In final 30–60 minutes of regular session
- When all 4 components are available
- For SPX/SPY/ES end-of-day positioning

## Inputs
- mocImbalance: MOC buy/sell imbalance (number)
- gex: gamma exposure by dealer (number)
- charmBid: charm bid strength 0–100 (number)
- odteSkew: 0DTE put/call skew (number)
- spotPrice: SPX level (number)
- timeToClose: minutes to 4:00 PM (number)

## Outputs
- signal: LONG | SHORT | FLAT (string)
- compositeScore: -100 to +100 (number)
- componentWeights: {moc, gex, charm, skew} (object)
- targetLevel: expected close range (number)
- confidence: 0–100 (number)

## Steps
1. Normalize: MOC long = +1, short = -1; GEX positive = +1 (dealers long gamma)
2. Charm bid positive = +1; 0DTE skew extreme put = -1 (fear)
3. Composite score = weighted sum: MOC 40%, GEX 25%, Charm 20%, Skew 15%
4. LONG when score > 30; SHORT when < -30; FLAT otherwise
5. Target = spot + expected drift from composite; confidence from agreement
6. Reduce size when components disagree; weight MOC higher in final 10 min

## Example
```yaml
inputs:
  mocImbalance: 800000
  gex: 0.12
  charmBid: 68
  odteSkew: 2.1
  timeToClose: 45
outputs:
  signal: LONG
  compositeScore: 52
  componentWeights: {moc: 0.4, gex: 0.25, charm: 0.2, skew: 0.15}
  targetLevel: 5855
  confidence: 78
```

## Notes
- Best used 30–60 min before close; MOC dominates in final 10 min
- Combine with correlation veto; avoid when DXY/VIX conflict

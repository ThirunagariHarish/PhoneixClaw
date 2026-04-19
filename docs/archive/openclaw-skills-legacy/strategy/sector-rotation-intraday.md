# Sector Rotation Intraday

## Purpose
Track intraday money flow rotation between sectors to identify leading and lagging groups.

## Category
strategy

## Triggers
- On 5–15 min bars for sector ETF flow
- When relative strength shifts between XLK, XLF, XLE, XLV, etc.
- When rotation confirms or contradicts broad market direction

## Inputs
- sectorFlows: [{symbol, flow, changePct}, ...] (array)
- spyPrice: SPY price (number)
- spyFlow: SPY net flow (number)
- timeframe: 5 | 15 (minutes) (number)

## Outputs
- leadingSectors: sectors with strongest flow (array)
- laggingSectors: sectors with weakest flow (array)
- rotationSignal: RISK_ON | RISK_OFF | NEUTRAL (string)
- topLong: preferred long sector (string)
- topShort: preferred short sector (string)

## Steps
1. Rank sectors by flow change and relative performance
2. Leading = top 2 by flow; lagging = bottom 2
3. RISK_ON when cyclical (XLF, XLE) lead; RISK_OFF when defensives (XLV, XLU) lead
4. Top long = leading sector; top short = lagging sector
5. Confirm with SPY flow; divergence = caution

## Example
```yaml
inputs:
  sectorFlows: [{symbol: XLK, flow: 12.5}, {symbol: XLF, flow: -3.2}, ...]
  timeframe: 15
outputs:
  leadingSectors: [XLK, XLY]
  laggingSectors: [XLF, XLE]
  rotationSignal: RISK_ON
  topLong: XLK
  topShort: XLF
```

## Notes
- Use sector ETFs or proxies; single-stock flow can be noisy
- Rotation can lag price; use as confirmation, not sole trigger

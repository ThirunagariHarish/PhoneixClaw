# Shadow Execution

## Purpose
Stealth execution that splits large orders and disguises participation to minimize market impact and information leakage.

## Category
strategy

## Triggers
- When order size exceeds 5% of ADV
- When executing block orders in liquid names
- When avoiding detection by HFT or other participants

## Inputs
- orderSize: total shares/contracts to execute (number)
- adv: average daily volume (number)
- urgency: LOW | MEDIUM | HIGH (string)
- currentSpread: bid-ask spread in ticks (number)

## Outputs
- childSizes: array of child order sizes (array)
- timingSchedule: millisecond intervals between children (array)
- participationCap: max % of bar volume per child (number)

## Steps
1. Compute participation rate: orderSize / ADV; cap at 2–5% per 5-min bar
2. Split into children using VWAP- or TWAP-style distribution
3. Add jitter to timing (Poisson or uniform) to avoid predictable patterns
4. Size children inversely to volatility; smaller in choppy markets
5. Output child order sequence with timing and size constraints

## Example
```yaml
inputs:
  orderSize: 50000
  adv: 80000000
  urgency: MEDIUM
outputs:
  childSizes: [1200, 800, 1500, 900, ...]
  participationCap: 0.03
  timingSchedule: [450, 620, 380, 510, ...]
```

## Notes
- Use limit orders when possible; avoid crossing spread on large prints
- Align with VWAP or arrival price benchmarks for performance measurement

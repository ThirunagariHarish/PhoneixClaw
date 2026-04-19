# Dynamic Gas Optimizer

## Purpose
Calculate optimal limit order price based on spread and congestion to save 0.5–1% slippage vs market orders.

## Category
strategy

## Triggers
- When placing limit orders
- When spread is wide or order book is thin
- When order size is meaningful relative to depth

## Inputs
- side: BUY | SELL (string)
- midPrice: current mid (number)
- spread: bid-ask spread in ticks (number)
- bookDepth: {bid: [price, size], ask: [price, size]} (object)
- orderSize: shares or contracts (number)
- urgency: LOW | MEDIUM | HIGH (string)

## Outputs
- limitPrice: recommended limit price (number)
- expectedFillPct: probability of fill (number)
- slippageSaved: estimated bps saved vs market (number)
- placement: MID | PASSIVE | AGGRESSIVE (string)

## Steps
1. Compute available depth at each level; estimate fill probability
2. LOW urgency: place at mid or slightly passive; wait for fill
3. MEDIUM: place 1–2 ticks aggressive for 50–70% fill probability
4. HIGH: place near or through touch; accept some slippage
5. limitPrice = level that maximizes (fillProb × priceImprovement)
6. slippageSaved = (marketSlippage - expectedLimitSlippage) in bps

## Example
```yaml
inputs:
  side: BUY
  midPrice: 450.25
  spread: 2
  urgency: MEDIUM
  orderSize: 500
outputs:
  limitPrice: 450.24
  expectedFillPct: 0.65
  slippageSaved: 8
  placement: PASSIVE
```

## Notes
- Works best in liquid names; illiquid books need more aggressive placement
- Rebalance limit if not filled within timeout

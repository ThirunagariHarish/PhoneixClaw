# Beta Hedging

## Purpose
Calculate and execute beta-weighted hedges to neutralize portfolio or position exposure to a benchmark (e.g., SPY) using futures or ETFs.

## Category
risk

## Triggers
- When the agent needs to hedge portfolio or position beta
- When user requests beta hedge or market-neutral adjustment
- When reducing directional exposure to a benchmark
- When managing systematic risk in a long/short portfolio

## Inputs
- `positions`: object[] — Positions to hedge: symbol, quantity, side, market_value
- `benchmark`: string — Benchmark symbol (default: "SPY")
- `hedge_instrument`: string — Hedge vehicle (e.g., "SPY", "SPX", "ES")
- `target_beta`: number — Target portfolio beta (default: 0 for full hedge)
- `lookback_days`: number — Days for beta calculation (default: 60)
- `account_value`: number — Total equity for sizing
- `returns_data`: object — Optional pre-fetched returns; if empty, fetch via market-data-fetcher

## Outputs
- `portfolio_beta`: number — Current portfolio beta to benchmark
- `hedge_quantity`: number — Shares/contracts of hedge instrument to trade
- `hedge_side`: string — "buy" or "sell" to achieve target beta
- `hedge_value`: number — Dollar value of hedge
- `validation`: object — Pass/fail, warnings (e.g., hedge too large)
- `metadata`: object — Benchmark, hedge_instrument, lookback_days, computed_at

## Steps
1. Fetch returns for each position and benchmark if not provided
2. Compute position betas: covariance(position_return, benchmark_return) / variance(benchmark_return)
3. Compute portfolio beta: weighted sum of position betas by market value
4. Compute beta to hedge: portfolio_beta - target_beta
5. Compute hedge instrument beta to benchmark (usually ~1 for SPY)
6. hedge_quantity = (beta_to_hedge * account_value) / (hedge_instrument_price * hedge_beta)
7. Determine hedge_side: if portfolio_beta > target, sell hedge; if < target, buy hedge
8. Validate: hedge_value not excessive vs account; flag if > 50% of account
9. Return portfolio_beta, hedge_quantity, hedge_side, hedge_value, validation, metadata
10. Pass hedge order to order-placer for execution

## Example
```
Input: positions=[{symbol: "NVDA", quantity: 100, market_value: 87500}], benchmark="SPY", target_beta=0, account_value=200000
Output: {
  portfolio_beta: 1.35,
  hedge_quantity: -135,
  hedge_side: "sell",
  hedge_value: 60750,
  validation: {pass: true, warnings: []},
  metadata: {benchmark: "SPY", hedge_instrument: "SPY", lookback_days: 60, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Beta is historical; may change in stress regimes
- Use futures (ES, NQ) for capital efficiency; adjust contract multiplier
- Rebalance periodically as positions and betas drift
